"""
Delivery Engine - orchestrates the fetch → generate → email pipeline.

State machine:
    PENDING → FETCHING → GENERATING → SENDING → SENT
                 ↓           ↓          ↓
               FAILED      FAILED     FAILED
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import Delivery, DeliveryStatus
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionType
from app.models.user import User
from app.services.calibre import CalibreError, CalibreWrapper
from app.services.smtp import (
    MAX_FILE_SIZE,
    SMTPConfig,
    SMTPError,
    send_kindle_email,
)

logger = logging.getLogger(__name__)


class DeliveryError(Exception):
    """Base exception for delivery pipeline errors."""

    pass


class DeliverySizeError(DeliveryError):
    """Generated file exceeds size limit."""

    pass


class DeliveryConfigError(DeliveryError):
    """User configuration is incomplete."""

    pass


@dataclass
class DeliveryResult:
    """Result of a delivery attempt."""

    delivery_id: int
    status: DeliveryStatus
    file_path: str | None = None
    file_size_bytes: int | None = None
    article_count: int | None = None
    error_stage: str | None = None
    error_message: str | None = None


class DeliveryEngine:
    """
    Orchestrates the delivery pipeline.

    Pipeline stages:
    1. Create Delivery record (PENDING)
    2. Fetch content via Calibre (FETCHING)
    3. Generate EPUB and validate size (GENERATING)
    4. Send via email (SENDING)
    5. Update status (SENT or FAILED)
    """

    def __init__(self, calibre: CalibreWrapper, epub_dir: Path):
        self.calibre = calibre
        self.epub_dir = epub_dir

    async def execute(
        self,
        db: AsyncSession,
        subscription: Subscription,
        user: User,
        scheduled_at: datetime | None = None,
        force: bool = False,
    ) -> DeliveryResult:
        """
        Execute full delivery pipeline for a subscription.

        Args:
            db: Database session
            subscription: The subscription to deliver
            user: The user who owns the subscription
            scheduled_at: When this delivery was scheduled (defaults to now)

        Returns:
            DeliveryResult with status and metadata

        Note:
            This method commits the Delivery record at each stage transition
            to ensure status is persisted even if the process crashes.
        """
        # Validate user configuration
        if not user.kindle_email:
            raise DeliveryConfigError("Kindle email not configured")

        if not user.smtp_config:
            raise DeliveryConfigError("SMTP settings not configured")

        now = datetime.now(timezone.utc)
        scheduled_at = scheduled_at or now

        # Check for same-day duplicate (skip check if force=True)
        if not force:
            existing = await self._check_already_sent_today(db, subscription.id)
        else:
            existing = None

        if existing:
            # Create a SKIPPED delivery record
            skipped_delivery = Delivery(
                subscription_id=subscription.id,
                user_id=user.id,
                status=DeliveryStatus.SKIPPED,
                scheduled_at=scheduled_at,
                started_at=now,
                completed_at=now,
                error_message=f"Already sent today (delivery #{existing.id})",
            )
            db.add(skipped_delivery)
            await db.flush()

            logger.info(
                f"Skipped delivery for '{subscription.name}': "
                f"already sent today (delivery #{existing.id})"
            )

            return DeliveryResult(
                delivery_id=skipped_delivery.id,
                status=DeliveryStatus.SKIPPED,
                error_message=f"Already sent today (delivery #{existing.id})",
            )

        # 1. Create delivery record (PENDING)
        delivery = Delivery(
            subscription_id=subscription.id,
            user_id=user.id,
            status=DeliveryStatus.PENDING,
            scheduled_at=scheduled_at,
        )
        db.add(delivery)
        await db.flush()

        logger.info(
            f"Starting delivery {delivery.id} for subscription '{subscription.name}'"
        )

        current_stage = "pending"
        output_path: Path | None = None

        try:
            # 2. FETCHING stage - run Calibre to fetch content
            current_stage = "fetching"
            await self._update_status(db, delivery, DeliveryStatus.FETCHING)

            output_path = self._generate_output_path(subscription, delivery)

            # Get settings from subscription (with defaults)
            settings = subscription.settings or {}
            max_articles = settings.get("max_articles", 25)
            oldest_days = settings.get("oldest_days", 7)
            include_images = settings.get("include_images", True)

            if subscription.type == SubscriptionType.RECIPE:
                await self.calibre.fetch_recipe(
                    recipe_name=subscription.source,
                    output_path=output_path,
                    max_articles=max_articles,
                    oldest_days=oldest_days,
                    include_images=include_images,
                )
            else:  # RSS
                await self.calibre.fetch_rss(
                    feed_url=subscription.source,
                    title=subscription.name,
                    output_path=output_path,
                    max_articles=max_articles,
                    oldest_days=oldest_days,
                    include_images=include_images,
                )

            # 3. GENERATING stage - validate size
            current_stage = "generating"
            await self._update_status(db, delivery, DeliveryStatus.GENERATING)

            file_size = output_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                raise DeliverySizeError(
                    f"File too large: {file_size / 1024 / 1024:.1f}MB exceeds 14MB limit"
                )

            logger.info(
                f"Delivery {delivery.id}: EPUB generated "
                f"({file_size / 1024:.1f} KB)"
            )

            # 4. SENDING stage - email to Kindle
            current_stage = "sending"
            await self._update_status(db, delivery, DeliveryStatus.SENDING)

            smtp_config = SMTPConfig.from_dict(user.smtp_config)
            await send_kindle_email(
                config=smtp_config,
                to_email=user.kindle_email,
                subject=f"Kindledrop: {subscription.name}",
                epub_path=output_path,
            )

            # 5. SUCCESS - update delivery and subscription
            delivery.status = DeliveryStatus.SENT
            delivery.completed_at = datetime.now(timezone.utc)
            delivery.file_path = str(output_path)
            delivery.file_size_bytes = file_size

            subscription.last_run_at = datetime.now(timezone.utc)
            subscription.last_status = SubscriptionStatus.SUCCESS
            subscription.last_error = None

            await db.flush()

            logger.info(
                f"Delivery {delivery.id} completed successfully: "
                f"'{subscription.name}' sent to {user.kindle_email}"
            )

            return DeliveryResult(
                delivery_id=delivery.id,
                status=DeliveryStatus.SENT,
                file_path=str(output_path),
                file_size_bytes=file_size,
            )

        except (CalibreError, SMTPError, DeliverySizeError, DeliveryConfigError) as e:
            # Handle known errors with clean messages
            await self._handle_failure(
                db, delivery, subscription, current_stage, str(e)
            )
            return DeliveryResult(
                delivery_id=delivery.id,
                status=DeliveryStatus.FAILED,
                error_stage=current_stage,
                error_message=str(e),
            )

        except Exception as e:
            # Handle unexpected errors
            logger.exception(f"Unexpected error in delivery {delivery.id}")
            error_msg = f"Unexpected error: {type(e).__name__}: {e}"
            await self._handle_failure(
                db, delivery, subscription, current_stage, error_msg
            )
            return DeliveryResult(
                delivery_id=delivery.id,
                status=DeliveryStatus.FAILED,
                error_stage=current_stage,
                error_message=error_msg,
            )

    def _generate_output_path(
        self, subscription: Subscription, delivery: Delivery
    ) -> Path:
        """Generate unique output path for EPUB file."""
        # Format: {epub_dir}/{subscription_id}_{delivery_id}_{timestamp}.epub
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{subscription.id}_{delivery.id}_{timestamp}.epub"
        return self.epub_dir / filename

    async def _update_status(
        self,
        db: AsyncSession,
        delivery: Delivery,
        status: DeliveryStatus,
    ) -> None:
        """Update delivery status and flush to database."""
        delivery.status = status
        if status == DeliveryStatus.FETCHING:
            delivery.started_at = datetime.now(timezone.utc)
        await db.flush()
        logger.debug(f"Delivery {delivery.id} status: {status.value}")

    async def _handle_failure(
        self,
        db: AsyncSession,
        delivery: Delivery,
        subscription: Subscription,
        stage: str,
        error_message: str,
    ) -> None:
        """Handle delivery failure - update delivery and subscription."""
        delivery.status = DeliveryStatus.FAILED
        delivery.completed_at = datetime.now(timezone.utc)
        delivery.error_stage = stage
        delivery.error_message = error_message[:1000]  # Truncate to fit DB field

        subscription.last_run_at = datetime.now(timezone.utc)
        subscription.last_status = SubscriptionStatus.FAILED
        subscription.last_error = error_message[:1000]

        await db.flush()

        logger.error(
            f"Delivery {delivery.id} failed at stage '{stage}': {error_message}"
        )

    async def _check_already_sent_today(
        self,
        db: AsyncSession,
        subscription_id: int,
    ) -> Delivery | None:
        """
        Check if a successful delivery exists for this subscription today (UTC).

        Returns the existing delivery if found, None otherwise.
        """
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        result = await db.execute(
            select(Delivery)
            .where(
                Delivery.subscription_id == subscription_id,
                Delivery.status == DeliveryStatus.SENT,
                Delivery.completed_at >= today_start,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
