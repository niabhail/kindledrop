"""Tests for scheduler service."""

from datetime import datetime
from datetime import timezone as dt_timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scheduler import (
    SchedulerService,
    calculate_next_run,
)


class TestCalculateNextRun:
    """Test calculate_next_run function."""

    def test_daily_schedule_future_time(self):
        """Daily schedule where time hasn't passed yet today."""
        schedule = {"type": "daily", "time": "23:00"}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        # Should be today at 23:00 UTC
        assert result is not None
        assert result.day == 15
        assert result.hour == 23
        assert result.minute == 0

    def test_daily_schedule_past_time(self):
        """Daily schedule where time has passed today."""
        schedule = {"type": "daily", "time": "07:00"}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        # Should be tomorrow at 07:00 UTC
        assert result is not None
        assert result.day == 16
        assert result.hour == 7
        assert result.minute == 0

    def test_daily_schedule_with_timezone(self):
        """Daily schedule respects user timezone."""
        schedule = {"type": "daily", "time": "07:00"}
        # At 10:00 UTC, it's 05:00 in New York (EST, UTC-5)
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "America/New_York", from_time=now)

        # 07:00 New York time = 12:00 UTC (during EST)
        assert result is not None
        assert result.tzinfo == dt_timezone.utc
        # Should be today since 07:00 EST hasn't passed yet (current local time is 05:00 EST)
        assert result.day == 15
        assert result.hour == 12  # 07:00 EST = 12:00 UTC

    def test_weekly_schedule_today_not_passed(self):
        """Weekly schedule for today's day, time not passed."""
        # January 15, 2024 is a Monday
        schedule = {"type": "weekly", "time": "23:00", "days": ["mon"]}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        # Should be today (Monday) at 23:00
        assert result is not None
        assert result.day == 15
        assert result.hour == 23

    def test_weekly_schedule_today_passed(self):
        """Weekly schedule for today's day, time already passed."""
        # January 15, 2024 is a Monday
        schedule = {"type": "weekly", "time": "07:00", "days": ["mon"]}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        # Should be next Monday (22nd) at 07:00
        assert result is not None
        assert result.day == 22
        assert result.hour == 7

    def test_weekly_schedule_multiple_days(self):
        """Weekly schedule with multiple days finds next occurrence."""
        # January 15, 2024 is a Monday
        schedule = {"type": "weekly", "time": "07:00", "days": ["wed", "fri"]}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        # Should be Wednesday (17th) at 07:00
        assert result is not None
        assert result.day == 17
        assert result.weekday() == 2  # Wednesday

    def test_interval_schedule_no_last_run(self):
        """Interval schedule with no previous run."""
        schedule = {"type": "interval", "interval_hours": 12}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)
        created = datetime(2024, 1, 15, 6, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(
            schedule, "UTC", from_time=now, last_run_at=None, created_at=created
        )

        # Should be created_at + 12 hours = 18:00
        assert result is not None
        assert result.hour == 18

    def test_interval_schedule_with_last_run(self):
        """Interval schedule uses last_run_at as base."""
        schedule = {"type": "interval", "interval_hours": 6}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)
        last_run = datetime(2024, 1, 15, 8, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(
            schedule, "UTC", from_time=now, last_run_at=last_run
        )

        # Should be last_run + 6 hours = 14:00
        assert result is not None
        assert result.hour == 14

    def test_interval_schedule_advances_past_now(self):
        """Interval schedule advances until future time."""
        schedule = {"type": "interval", "interval_hours": 2}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)
        last_run = datetime(2024, 1, 15, 4, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(
            schedule, "UTC", from_time=now, last_run_at=last_run
        )

        # 4 + 2 = 6, 6 + 2 = 8, 8 + 2 = 10 (not future), 10 + 2 = 12 (future!)
        assert result is not None
        assert result.hour == 12

    def test_manual_schedule_returns_none(self):
        """Manual schedule returns None (no automatic scheduling)."""
        schedule = {"type": "manual"}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        assert result is None

    def test_invalid_timezone_falls_back_to_utc(self):
        """Invalid timezone falls back to UTC."""
        schedule = {"type": "daily", "time": "07:00"}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        # Should not raise, should fall back to UTC
        result = calculate_next_run(schedule, "Invalid/Timezone", from_time=now)

        assert result is not None
        # Tomorrow 07:00 UTC
        assert result.day == 16
        assert result.hour == 7

    def test_unknown_schedule_type_returns_none(self):
        """Unknown schedule type returns None."""
        schedule = {"type": "unknown_type"}
        now = datetime(2024, 1, 15, 10, 0, tzinfo=dt_timezone.utc)

        result = calculate_next_run(schedule, "UTC", from_time=now)

        assert result is None


class TestSchedulerService:
    """Test SchedulerService class."""

    @pytest.fixture
    def mock_delivery_engine(self):
        """Mock delivery engine."""
        engine = MagicMock()
        engine.execute = AsyncMock()
        return engine

    @pytest.fixture
    def scheduler_service(self, mock_delivery_engine):
        """Create scheduler service with mocked dependencies."""
        return SchedulerService(delivery_engine=mock_delivery_engine)

    async def test_start_and_stop(self, scheduler_service):
        """Test scheduler start and stop."""
        with patch.object(scheduler_service, "_fix_stale_schedules", new_callable=AsyncMock):
            await scheduler_service.start()
            assert scheduler_service._running is True
            assert scheduler_service.scheduler.running is True

            await scheduler_service.stop()
            assert scheduler_service._running is False

    async def test_start_twice_warns(self, scheduler_service):
        """Starting twice should warn and not duplicate."""
        with patch.object(scheduler_service, "_fix_stale_schedules", new_callable=AsyncMock):
            await scheduler_service.start()
            await scheduler_service.start()  # Should just warn

            assert scheduler_service._running is True
            await scheduler_service.stop()

    async def test_stop_when_not_running(self, scheduler_service):
        """Stopping when not running should be safe."""
        await scheduler_service.stop()  # Should not raise
        assert scheduler_service._running is False
