"""Tests for Delivery Engine service."""

from unittest.mock import patch

import pytest

from app.models import DeliveryStatus, SubscriptionStatus
from app.services.delivery import (
    DeliveryConfigError,
    DeliveryEngine,
    DeliveryResult,
)


class TestDeliveryEngine:
    """Test DeliveryEngine class."""

    async def test_execute_success(
        self, db_session, test_user, test_subscription, mock_calibre_fetch, mock_smtp, tmp_path
    ):
        """Test successful delivery pipeline."""
        from app.services.calibre import calibre

        engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)

        result = await engine.execute(
            db=db_session,
            subscription=test_subscription,
            user=test_user,
        )

        assert result.status == DeliveryStatus.SENT
        assert result.delivery_id is not None
        assert result.file_size_bytes is not None
        mock_smtp.assert_called_once()

    async def test_execute_missing_kindle_email(
        self, db_session, test_subscription, tmp_path
    ):
        """Test error when user has no Kindle email configured."""
        from app.models import User
        from app.services.calibre import calibre

        # Create user without kindle_email
        # Use pre-computed bcrypt hash to avoid passlib/bcrypt compatibility issues
        user = User(
            username="nokindleuser",
            email="nokindleuser@example.com",
            password_hash="$2b$12$test.hash.for.testing.purposes.only",
            kindle_email=None,
            smtp_config={"host": "smtp.test.com", "port": 587, "username": "u", "password": "p", "from_email": "f@t.com"},
        )
        db_session.add(user)
        await db_session.flush()

        # Update subscription to this user
        test_subscription.user_id = user.id
        await db_session.flush()

        engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)

        with pytest.raises(DeliveryConfigError, match="Kindle email not configured"):
            await engine.execute(
                db=db_session,
                subscription=test_subscription,
                user=user,
            )

    async def test_execute_missing_smtp_config(
        self, db_session, test_subscription, tmp_path
    ):
        """Test error when user has no SMTP config."""
        from app.models import User
        from app.services.calibre import calibre

        # Create user without smtp_config
        # Use pre-computed bcrypt hash to avoid passlib/bcrypt compatibility issues
        user = User(
            username="nosmtpuser",
            email="nosmtpuser@example.com",
            password_hash="$2b$12$test.hash.for.testing.purposes.only",
            kindle_email="test@kindle.com",
            smtp_config=None,
        )
        db_session.add(user)
        await db_session.flush()

        # Update subscription to this user
        test_subscription.user_id = user.id
        await db_session.flush()

        engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)

        with pytest.raises(DeliveryConfigError, match="SMTP settings not configured"):
            await engine.execute(
                db=db_session,
                subscription=test_subscription,
                user=user,
            )

    async def test_execute_calibre_failure(
        self, db_session, test_user, test_subscription, mock_smtp, tmp_path
    ):
        """Test handling of Calibre failure."""
        from app.services.calibre import CalibreError, calibre

        engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)

        with patch.object(calibre, "fetch_recipe", side_effect=CalibreError("Recipe failed")):
            result = await engine.execute(
                db=db_session,
                subscription=test_subscription,
                user=test_user,
            )

        assert result.status == DeliveryStatus.FAILED
        assert result.error_stage == "fetching"
        assert "Recipe failed" in result.error_message

    async def test_delivery_creates_record(
        self, db_session, test_user, test_subscription, mock_calibre_fetch, mock_smtp, tmp_path
    ):
        """Test that delivery creates a Delivery record in database."""
        from sqlalchemy import select

        from app.models import Delivery
        from app.services.calibre import calibre

        engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)

        result = await engine.execute(
            db=db_session,
            subscription=test_subscription,
            user=test_user,
        )

        # Check delivery was created
        query = select(Delivery).where(Delivery.id == result.delivery_id)
        delivery_result = await db_session.execute(query)
        delivery = delivery_result.scalar_one()

        assert delivery is not None
        assert delivery.subscription_id == test_subscription.id
        assert delivery.user_id == test_user.id
        assert delivery.status == DeliveryStatus.SENT

    async def test_delivery_updates_subscription_tracking(
        self, db_session, test_user, test_subscription, mock_calibre_fetch, mock_smtp, tmp_path
    ):
        """Test that successful delivery updates subscription tracking fields."""
        from app.services.calibre import calibre

        # Ensure initial state
        assert test_subscription.last_run_at is None
        assert test_subscription.last_status is None

        engine = DeliveryEngine(calibre=calibre, epub_dir=tmp_path)

        await engine.execute(
            db=db_session,
            subscription=test_subscription,
            user=test_user,
        )

        # Refresh to get updated values
        await db_session.refresh(test_subscription)

        assert test_subscription.last_run_at is not None
        assert test_subscription.last_status == SubscriptionStatus.SUCCESS
        assert test_subscription.last_error is None


class TestDeliveryResult:
    """Test DeliveryResult dataclass."""

    def test_success_result(self):
        result = DeliveryResult(
            delivery_id=1,
            status=DeliveryStatus.SENT,
            file_path="/path/to/file.epub",
            file_size_bytes=1024,
        )
        assert result.delivery_id == 1
        assert result.status == DeliveryStatus.SENT
        assert result.error_stage is None
        assert result.error_message is None

    def test_failure_result(self):
        result = DeliveryResult(
            delivery_id=2,
            status=DeliveryStatus.FAILED,
            error_stage="fetching",
            error_message="Recipe failed to fetch",
        )
        assert result.delivery_id == 2
        assert result.status == DeliveryStatus.FAILED
        assert result.error_stage == "fetching"
        assert result.error_message == "Recipe failed to fetch"
