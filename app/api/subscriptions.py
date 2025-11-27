from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession
from app.models import Subscription, SubscriptionType

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class ScheduleConfig(BaseModel):
    type: str = "daily"  # daily, weekly, interval, manual
    time: str = "07:00"
    days: list[str] | None = None  # for weekly
    interval_hours: int | None = None  # for interval


class SettingsConfig(BaseModel):
    max_articles: int = 25
    oldest_days: int = 7
    include_images: bool = True
    title_override: str | None = None


class SubscriptionCreate(BaseModel):
    type: SubscriptionType
    source: str
    name: str
    schedule: ScheduleConfig = ScheduleConfig()
    settings: SettingsConfig = SettingsConfig()


class SubscriptionUpdate(BaseModel):
    name: str | None = None
    schedule: ScheduleConfig | None = None
    settings: SettingsConfig | None = None


class SubscriptionResponse(BaseModel):
    id: int
    type: str
    source: str
    name: str
    enabled: bool
    schedule: dict
    settings: dict
    last_run_at: str | None
    last_status: str | None
    next_run_at: str | None

    class Config:
        from_attributes = True


@router.get("")
async def list_subscriptions(
    user: CurrentUser,
    db: DbSession,
) -> list[SubscriptionResponse]:
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    subscriptions = result.scalars().all()
    return [
        SubscriptionResponse(
            id=s.id,
            type=s.type.value if isinstance(s.type, SubscriptionType) else s.type,
            source=s.source,
            name=s.name,
            enabled=s.enabled,
            schedule=s.schedule,
            settings=s.settings,
            last_run_at=s.last_run_at.isoformat() if s.last_run_at else None,
            last_status=s.last_status.value if s.last_status else None,
            next_run_at=s.next_run_at.isoformat() if s.next_run_at else None,
        )
        for s in subscriptions
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    request: SubscriptionCreate,
    user: CurrentUser,
    db: DbSession,
) -> SubscriptionResponse:
    subscription = Subscription(
        user_id=user.id,
        type=request.type,
        source=request.source,
        name=request.name,
        schedule=request.schedule.model_dump(),
        settings=request.settings.model_dump(),
    )
    db.add(subscription)
    await db.flush()
    await db.refresh(subscription)

    return SubscriptionResponse(
        id=subscription.id,
        type=subscription.type.value,
        source=subscription.source,
        name=subscription.name,
        enabled=subscription.enabled,
        schedule=subscription.schedule,
        settings=subscription.settings,
        last_run_at=None,
        last_status=None,
        next_run_at=None,
    )


@router.get("/{subscription_id}")
async def get_subscription(
    subscription_id: int,
    user: CurrentUser,
    db: DbSession,
) -> SubscriptionResponse:
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return SubscriptionResponse(
        id=subscription.id,
        type=subscription.type.value if isinstance(subscription.type, SubscriptionType) else subscription.type,
        source=subscription.source,
        name=subscription.name,
        enabled=subscription.enabled,
        schedule=subscription.schedule,
        settings=subscription.settings,
        last_run_at=subscription.last_run_at.isoformat() if subscription.last_run_at else None,
        last_status=subscription.last_status.value if subscription.last_status else None,
        next_run_at=subscription.next_run_at.isoformat() if subscription.next_run_at else None,
    )


@router.put("/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    request: SubscriptionUpdate,
    user: CurrentUser,
    db: DbSession,
) -> SubscriptionResponse:
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if request.name is not None:
        subscription.name = request.name
    if request.schedule is not None:
        subscription.schedule = request.schedule.model_dump()
    if request.settings is not None:
        subscription.settings = request.settings.model_dump()

    await db.flush()
    await db.refresh(subscription)

    return SubscriptionResponse(
        id=subscription.id,
        type=subscription.type.value if isinstance(subscription.type, SubscriptionType) else subscription.type,
        source=subscription.source,
        name=subscription.name,
        enabled=subscription.enabled,
        schedule=subscription.schedule,
        settings=subscription.settings,
        last_run_at=subscription.last_run_at.isoformat() if subscription.last_run_at else None,
        last_status=subscription.last_status.value if subscription.last_status else None,
        next_run_at=subscription.next_run_at.isoformat() if subscription.next_run_at else None,
    )


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: int,
    user: CurrentUser,
    db: DbSession,
) -> None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    await db.delete(subscription)


@router.post("/{subscription_id}/toggle")
async def toggle_subscription(
    subscription_id: int,
    user: CurrentUser,
    db: DbSession,
) -> SubscriptionResponse:
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    subscription.enabled = not subscription.enabled
    await db.flush()
    await db.refresh(subscription)

    return SubscriptionResponse(
        id=subscription.id,
        type=subscription.type.value if isinstance(subscription.type, SubscriptionType) else subscription.type,
        source=subscription.source,
        name=subscription.name,
        enabled=subscription.enabled,
        schedule=subscription.schedule,
        settings=subscription.settings,
        last_run_at=subscription.last_run_at.isoformat() if subscription.last_run_at else None,
        last_status=subscription.last_status.value if subscription.last_status else None,
        next_run_at=subscription.next_run_at.isoformat() if subscription.next_run_at else None,
    )
