"""
Scheduler Service - manages automatic scheduled deliveries.

Uses a single polling job that queries the database every 60 seconds
for subscriptions that are due. This approach keeps the database as
the source of truth and simplifies subscription management.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session_factory
from app.models import Delivery, Subscription, User
from app.services.delivery import DeliveryEngine

logger = logging.getLogger(__name__)


def calculate_next_run(
    schedule: dict,
    timezone: str,
    from_time: datetime | None = None,
    last_run_at: datetime | None = None,
    created_at: datetime | None = None,
) -> datetime | None:
    """
    Calculate the next run time based on schedule configuration.

    Schedule types:
    - {"type": "daily", "time": "07:00"} - Daily at specified time
    - {"type": "weekly", "time": "09:00", "days": ["sat", "sun"]} - Weekly on specific days
    - {"type": "interval", "interval_hours": 12} - Every N hours from last run
    - {"type": "manual"} - No automatic scheduling (Send Now only)

    Args:
        schedule: Schedule configuration dict
        timezone: User's timezone (e.g., "America/New_York")
        from_time: Base time for calculation (defaults to now)
        last_run_at: Last successful run time (for interval schedules)
        created_at: Subscription creation time (fallback for intervals)

    Returns:
        Next run datetime (UTC) or None for manual schedules
    """
    schedule_type = schedule.get("type", "daily")

    if schedule_type == "manual":
        return None

    # Get user's timezone
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        logger.warning(f"Invalid timezone '{timezone}', falling back to UTC")
        tz = ZoneInfo("UTC")

    # Base time in UTC (default to now)
    now_utc = from_time or datetime.now(dt_timezone.utc)
    now_local = now_utc.astimezone(tz)

    if schedule_type == "daily":
        return _calculate_daily_next_run(schedule, now_local, tz)

    elif schedule_type == "weekly":
        return _calculate_weekly_next_run(schedule, now_local, tz)

    elif schedule_type == "interval":
        return _calculate_interval_next_run(
            schedule, now_utc, last_run_at, created_at
        )

    else:
        logger.warning(f"Unknown schedule type: {schedule_type}")
        return None


def _calculate_daily_next_run(
    schedule: dict,
    now_local: datetime,
    tz: ZoneInfo,
) -> datetime:
    """Calculate next daily run time."""
    time_str = schedule.get("time", "07:00")
    hour, minute = map(int, time_str.split(":"))

    # Create target time today in user's timezone
    target_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If target time has passed today, schedule for tomorrow
    if target_local <= now_local:
        target_local += timedelta(days=1)

    # Convert to UTC
    return target_local.astimezone(dt_timezone.utc)


def _calculate_weekly_next_run(
    schedule: dict,
    now_local: datetime,
    tz: ZoneInfo,
) -> datetime:
    """Calculate next weekly run time."""
    time_str = schedule.get("time", "07:00")
    days = schedule.get("days", ["mon"])

    hour, minute = map(int, time_str.split(":"))

    # Map day names to weekday numbers (0=Monday, 6=Sunday)
    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    target_weekdays = sorted([day_map.get(d.lower(), 0) for d in days])

    if not target_weekdays:
        target_weekdays = [0]  # Default to Monday

    # Start checking from today
    check_date = now_local.date()
    current_weekday = check_date.weekday()

    # Check up to 8 days ahead to find next occurrence
    for days_ahead in range(8):
        candidate_weekday = (current_weekday + days_ahead) % 7
        if candidate_weekday in target_weekdays:
            candidate_date = check_date + timedelta(days=days_ahead)
            candidate_local = datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                hour,
                minute,
                0,
                tzinfo=tz,
            )

            # If it's today but time has passed, continue to next occurrence
            if candidate_local > now_local:
                return candidate_local.astimezone(dt_timezone.utc)

    # Fallback: next week's first target day
    days_until = (target_weekdays[0] - current_weekday + 7) % 7 or 7
    next_date = check_date + timedelta(days=days_until)
    next_local = datetime(
        next_date.year, next_date.month, next_date.day, hour, minute, 0, tzinfo=tz
    )
    return next_local.astimezone(dt_timezone.utc)


def _calculate_interval_next_run(
    schedule: dict,
    now_utc: datetime,
    last_run_at: datetime | None,
    created_at: datetime | None,
) -> datetime:
    """Calculate next interval run time."""
    interval_hours = schedule.get("interval_hours", 12)
    interval = timedelta(hours=interval_hours)

    # Base time: prefer last_run_at, fallback to created_at, then now
    if last_run_at:
        base_time = last_run_at
    elif created_at:
        base_time = created_at
    else:
        base_time = now_utc

    # Ensure base_time is timezone-aware
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=dt_timezone.utc)

    # Calculate next run
    next_run = base_time + interval

    # If next_run is in the past, advance until it's in the future
    while next_run <= now_utc:
        next_run += interval

    return next_run


class SchedulerService:
    """
    Manages scheduled deliveries using APScheduler.

    Uses a single polling job that queries the database every minute
    for subscriptions where next_run_at <= now. This approach:
    - Keeps database as source of truth
    - Makes subscription changes instant (no job recreation)
    - Handles app restarts gracefully
    - Is easy to reason about
    """

    def __init__(self, delivery_engine: DeliveryEngine):
        self.scheduler = AsyncIOScheduler()
        self.delivery_engine = delivery_engine
        self._semaphore = asyncio.Semaphore(settings.scheduler_max_concurrent)
        self._running = False

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Fix any stale schedules before starting
        await self._fix_stale_schedules()

        # Add the polling job
        self.scheduler.add_job(
            self._poll_and_dispatch,
            trigger=IntervalTrigger(seconds=settings.scheduler_poll_interval),
            id="poll_subscriptions",
            replace_existing=True,
            max_instances=1,  # Don't overlap polling runs
        )

        # Add the daily cleanup job (runs at 3 AM UTC)
        self.scheduler.add_job(
            self._cleanup_retention,
            trigger=CronTrigger(hour=3, minute=0),
            id="cleanup_retention",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.start()
        self._running = True
        logger.info(
            f"Scheduler started: polling every {settings.scheduler_poll_interval}s, "
            f"max {settings.scheduler_max_concurrent} concurrent deliveries"
        )
        logger.info(
            f"Retention cleanup: EPUBs after {settings.epub_retention_hours}h, "
            f"records after {settings.delivery_retention_days} days"
        )

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Scheduler stopped")

    async def _fix_stale_schedules(self) -> None:
        """
        On startup, fix any subscriptions with next_run_at in the past.

        Design decision: We SKIP missed runs rather than catching up.
        Since Calibre fetches content live, we can't deliver "what was
        available yesterday" - so better to just schedule the next run.
        """
        async with async_session_factory() as db:
            now = datetime.now(dt_timezone.utc)

            result = await db.execute(
                select(Subscription)
                .options(selectinload(Subscription.user))
                .where(
                    Subscription.next_run_at < now,
                    Subscription.next_run_at.isnot(None),
                    Subscription.enabled.is_(True),
                )
            )
            stale_subs = result.scalars().all()

            if not stale_subs:
                return

            logger.info(f"Fixing {len(stale_subs)} stale schedules (skipping missed runs)")

            for sub in stale_subs:
                new_next_run = calculate_next_run(
                    sub.schedule,
                    sub.user.timezone,
                    from_time=now,
                    last_run_at=sub.last_run_at,
                    created_at=sub.created_at,
                )
                sub.next_run_at = new_next_run
                logger.debug(
                    f"Subscription {sub.id} '{sub.name}': "
                    f"rescheduled to {new_next_run}"
                )

            await db.commit()

    async def _poll_and_dispatch(self) -> None:
        """Poll for due subscriptions and dispatch deliveries."""
        async with async_session_factory() as db:
            now = datetime.now(dt_timezone.utc)

            # Find subscriptions that are due
            result = await db.execute(
                select(Subscription)
                .options(selectinload(Subscription.user))
                .where(
                    Subscription.next_run_at <= now,
                    Subscription.next_run_at.isnot(None),
                    Subscription.enabled.is_(True),
                )
            )
            due_subs = result.scalars().all()

            if not due_subs:
                return

            logger.info(f"Found {len(due_subs)} due subscription(s)")

            # Dispatch deliveries concurrently (limited by semaphore)
            tasks = [
                self._execute_with_semaphore(sub, sub.user)
                for sub in due_subs
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_with_semaphore(
        self,
        subscription: Subscription,
        user: User,
    ) -> None:
        """Execute a delivery with concurrency limiting."""
        async with self._semaphore:
            async with async_session_factory() as db:
                try:
                    # Re-fetch subscription in this session
                    result = await db.execute(
                        select(Subscription)
                        .options(selectinload(Subscription.user))
                        .where(Subscription.id == subscription.id)
                    )
                    sub = result.scalar_one_or_none()

                    if not sub:
                        logger.warning(
                            f"Subscription {subscription.id} not found during delivery"
                        )
                        return

                    # Re-fetch user in this session
                    result = await db.execute(
                        select(User).where(User.id == user.id)
                    )
                    usr = result.scalar_one_or_none()

                    if not usr:
                        logger.warning(f"User {user.id} not found during delivery")
                        return

                    scheduled_at = sub.next_run_at

                    # Execute delivery
                    logger.info(f"Starting scheduled delivery for '{sub.name}'")
                    delivery_result = await self.delivery_engine.execute(
                        db=db,
                        subscription=sub,
                        user=usr,
                        scheduled_at=scheduled_at,
                    )

                    # Calculate and set next run time
                    sub.next_run_at = calculate_next_run(
                        sub.schedule,
                        usr.timezone,
                        from_time=datetime.now(dt_timezone.utc),
                        last_run_at=sub.last_run_at,
                        created_at=sub.created_at,
                    )

                    await db.commit()

                    if delivery_result.error_message:
                        logger.warning(
                            f"Delivery for '{sub.name}' failed: {delivery_result.error_message}"
                        )
                    else:
                        logger.info(
                            f"Delivery for '{sub.name}' completed, "
                            f"next run: {sub.next_run_at}"
                        )

                except Exception as e:
                    logger.exception(
                        f"Error in scheduled delivery for subscription {subscription.id}: {e}"
                    )

    async def _cleanup_retention(self) -> None:
        """
        Clean up old EPUB files and delivery records.

        - EPUB files: deleted after epub_retention_hours (default 24h)
        - Delivery records: deleted after delivery_retention_days (default 30 days)

        Files are cleaned first so records can be deleted without orphaning references.
        """
        now = datetime.now(dt_timezone.utc)
        epub_cutoff = now - timedelta(hours=settings.epub_retention_hours)
        record_cutoff = now - timedelta(days=settings.delivery_retention_days)

        files_deleted = 0
        records_deleted = 0

        async with async_session_factory() as db:
            try:
                # 1. Clean up EPUB files older than retention period
                # Find deliveries with file_path that are old enough to clean
                result = await db.execute(
                    select(Delivery).where(
                        Delivery.file_path.isnot(None),
                        Delivery.completed_at < epub_cutoff,
                    )
                )
                old_deliveries = result.scalars().all()

                for delivery in old_deliveries:
                    if delivery.file_path:
                        file_path = Path(delivery.file_path)
                        if file_path.exists():
                            try:
                                file_path.unlink()
                                files_deleted += 1
                                logger.debug(f"Deleted EPUB: {file_path}")
                            except OSError as e:
                                logger.warning(f"Failed to delete {file_path}: {e}")

                        # Clear file_path so we don't try to delete again
                        delivery.file_path = None

                await db.commit()

                # 2. Delete old delivery records (older than retention period)
                result = await db.execute(
                    delete(Delivery).where(Delivery.created_at < record_cutoff)
                )
                records_deleted = result.rowcount
                await db.commit()

                if files_deleted > 0 or records_deleted > 0:
                    logger.info(
                        f"Retention cleanup: {files_deleted} EPUB files deleted, "
                        f"{records_deleted} delivery records deleted"
                    )

            except Exception as e:
                logger.exception(f"Error during retention cleanup: {e}")
