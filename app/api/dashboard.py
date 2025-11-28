"""Dashboard API endpoints for aggregated status data."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select

from app.dependencies import CurrentUser, DbSession
from app.models import Delivery, DeliveryStatus, Subscription

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class UpcomingDelivery(BaseModel):
    """An upcoming scheduled delivery."""

    subscription_id: int
    subscription_name: str
    next_run_at: str
    schedule_type: str
    enabled: bool


class RecentDelivery(BaseModel):
    """A recent delivery attempt."""

    delivery_id: int
    subscription_id: int
    subscription_name: str
    status: str
    completed_at: str | None
    error_message: str | None
    file_size_bytes: int | None
    article_count: int | None


class FailingSubscription(BaseModel):
    """A subscription with repeated failures."""

    subscription_id: int
    subscription_name: str
    consecutive_failures: int
    last_error: str | None


class SubscriptionHealth(BaseModel):
    """Aggregate health statistics for subscriptions."""

    total: int
    active: int
    paused: int
    failing: int
    failing_subscriptions: list[FailingSubscription]


class DailyStats(BaseModel):
    """Statistics for today's deliveries."""

    total_today: int
    successful_today: int
    failed_today: int


class DashboardResponse(BaseModel):
    """Aggregated dashboard data."""

    upcoming_deliveries: list[UpcomingDelivery]
    recent_activity: list[RecentDelivery]
    subscription_health: SubscriptionHealth
    stats: DailyStats


@router.get("")
async def get_dashboard(
    user: CurrentUser,
    db: DbSession,
) -> DashboardResponse:
    """
    Get aggregated dashboard data.

    Returns upcoming deliveries (next 24h), recent activity (last 10),
    subscription health statistics, and daily delivery stats.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_24h = now + timedelta(hours=24)

    # Upcoming deliveries (next 24 hours)
    upcoming_result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.enabled == True,
            Subscription.next_run_at != None,
            Subscription.next_run_at <= next_24h,
        )
        .order_by(Subscription.next_run_at)
    )
    upcoming_subs = upcoming_result.scalars().all()

    upcoming_deliveries = [
        UpcomingDelivery(
            subscription_id=s.id,
            subscription_name=s.name,
            next_run_at=s.next_run_at.isoformat() if s.next_run_at else "",
            schedule_type=s.schedule.get("type", "manual"),
            enabled=s.enabled,
        )
        for s in upcoming_subs
    ]

    # Recent activity (last 10 deliveries)
    recent_result = await db.execute(
        select(Delivery, Subscription.name)
        .join(Subscription, Delivery.subscription_id == Subscription.id)
        .where(Delivery.user_id == user.id)
        .order_by(desc(Delivery.created_at))
        .limit(10)
    )
    recent_rows = recent_result.all()

    recent_activity = [
        RecentDelivery(
            delivery_id=d.id,
            subscription_id=d.subscription_id,
            subscription_name=name,
            status=d.status.value if isinstance(d.status, DeliveryStatus) else d.status,
            completed_at=d.completed_at.isoformat() if d.completed_at else None,
            error_message=d.error_message,
            file_size_bytes=d.file_size_bytes,
            article_count=d.article_count,
        )
        for d, name in recent_rows
    ]

    # Subscription health - calculate failing subscriptions
    # "Failing" = 2+ consecutive failures (check last 3 deliveries per subscription)
    all_subs_result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    all_subs = all_subs_result.scalars().all()

    total_subs = len(all_subs)
    active_subs = sum(1 for s in all_subs if s.enabled)
    paused_subs = total_subs - active_subs

    # Find failing subscriptions by checking recent deliveries
    failing_subscriptions: list[FailingSubscription] = []

    for sub in all_subs:
        # Get last 3 deliveries for this subscription
        last_deliveries_result = await db.execute(
            select(Delivery)
            .where(Delivery.subscription_id == sub.id)
            .order_by(desc(Delivery.created_at))
            .limit(3)
        )
        last_deliveries = last_deliveries_result.scalars().all()

        # Count consecutive failures from most recent
        consecutive_failures = 0
        for delivery in last_deliveries:
            if delivery.status == DeliveryStatus.FAILED:
                consecutive_failures += 1
            else:
                break

        if consecutive_failures >= 2:
            failing_subscriptions.append(
                FailingSubscription(
                    subscription_id=sub.id,
                    subscription_name=sub.name,
                    consecutive_failures=consecutive_failures,
                    last_error=sub.last_error,
                )
            )

    subscription_health = SubscriptionHealth(
        total=total_subs,
        active=active_subs,
        paused=paused_subs,
        failing=len(failing_subscriptions),
        failing_subscriptions=failing_subscriptions,
    )

    # Daily stats
    today_result = await db.execute(
        select(
            func.count(Delivery.id).label("total"),
            func.sum(
                func.cast(Delivery.status == DeliveryStatus.SENT, db.bind.dialect.name == "sqlite" and "INTEGER" or "INT")
            ).label("successful"),
            func.sum(
                func.cast(Delivery.status == DeliveryStatus.FAILED, db.bind.dialect.name == "sqlite" and "INTEGER" or "INT")
            ).label("failed"),
        )
        .where(
            Delivery.user_id == user.id,
            Delivery.created_at >= today_start,
        )
    )
    today_stats = today_result.first()

    # Simpler approach - just count
    total_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user.id,
            Delivery.created_at >= today_start,
        )
    )
    successful_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user.id,
            Delivery.created_at >= today_start,
            Delivery.status == DeliveryStatus.SENT,
        )
    )
    failed_today_result = await db.execute(
        select(func.count(Delivery.id)).where(
            Delivery.user_id == user.id,
            Delivery.created_at >= today_start,
            Delivery.status == DeliveryStatus.FAILED,
        )
    )

    stats = DailyStats(
        total_today=total_today_result.scalar() or 0,
        successful_today=successful_today_result.scalar() or 0,
        failed_today=failed_today_result.scalar() or 0,
    )

    return DashboardResponse(
        upcoming_deliveries=upcoming_deliveries,
        recent_activity=recent_activity,
        subscription_health=subscription_health,
        stats=stats,
    )
