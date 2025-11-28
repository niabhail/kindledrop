from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update

from app.dependencies import CurrentUser, DbSession, DeliveryEngineDep
from app.models import DeliveryStatus, Subscription, SubscriptionType
from app.services.delivery import DeliveryConfigError
from app.services.scheduler import calculate_next_run

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
    model_config = ConfigDict(from_attributes=True)

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
    schedule_dict = request.schedule.model_dump()

    # Calculate initial next_run_at
    next_run = calculate_next_run(
        schedule=schedule_dict,
        timezone=user.timezone,
    )

    subscription = Subscription(
        user_id=user.id,
        type=request.type,
        source=request.source,
        name=request.name,
        schedule=schedule_dict,
        settings=request.settings.model_dump(),
        next_run_at=next_run,
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
        next_run_at=subscription.next_run_at.isoformat() if subscription.next_run_at else None,
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
        # Recalculate next_run_at when schedule changes
        subscription.next_run_at = calculate_next_run(
            schedule=subscription.schedule,
            timezone=user.timezone,
            last_run_at=subscription.last_run_at,
            created_at=subscription.created_at,
        )
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

    # When enabling, recalculate next_run_at in case it was stale
    if subscription.enabled:
        subscription.next_run_at = calculate_next_run(
            schedule=subscription.schedule,
            timezone=user.timezone,
            last_run_at=subscription.last_run_at,
            created_at=subscription.created_at,
        )

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


class SendNowResponse(BaseModel):
    """Response model for Send Now action."""

    delivery_id: int
    status: str
    message: str
    error_stage: str | None = None
    error_message: str | None = None


@router.post("/{subscription_id}/send")
async def send_now(
    subscription_id: int,
    user: CurrentUser,
    db: DbSession,
    engine: DeliveryEngineDep,
) -> SendNowResponse:
    """
    Trigger immediate delivery for a subscription.

    Executes the full delivery pipeline synchronously:
    fetch -> generate EPUB -> send via email.
    """
    # Get subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )

    # Validate user configuration
    if not user.kindle_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please configure your Kindle email address in settings first",
        )

    if not user.smtp_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please configure SMTP settings first",
        )

    try:
        # Execute delivery
        delivery_result = await engine.execute(
            db=db,
            subscription=subscription,
            user=user,
        )

        if delivery_result.status == DeliveryStatus.SENT:
            return SendNowResponse(
                delivery_id=delivery_result.delivery_id,
                status="sent",
                message=f"'{subscription.name}' sent to {user.kindle_email}",
            )
        else:
            return SendNowResponse(
                delivery_id=delivery_result.delivery_id,
                status="failed",
                message=f"Delivery failed at {delivery_result.error_stage} stage",
                error_stage=delivery_result.error_stage,
                error_message=delivery_result.error_message,
            )

    except DeliveryConfigError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


class PauseAllResponse(BaseModel):
    """Response model for pause-all/resume-all actions."""

    action: str
    affected: int


@router.post("/pause-all")
async def pause_all_subscriptions(
    user: CurrentUser,
    db: DbSession,
) -> PauseAllResponse:
    """Pause all active subscriptions for the current user."""
    result = await db.execute(
        update(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.enabled == True,
        )
        .values(enabled=False)
    )
    await db.commit()

    return PauseAllResponse(
        action="paused",
        affected=result.rowcount,
    )


@router.post("/resume-all")
async def resume_all_subscriptions(
    user: CurrentUser,
    db: DbSession,
) -> PauseAllResponse:
    """Resume all paused subscriptions for the current user."""
    # First get all paused subscriptions to recalculate next_run_at
    paused_result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.enabled == False,
        )
    )
    paused_subs = paused_result.scalars().all()

    count = 0
    for sub in paused_subs:
        sub.enabled = True
        sub.next_run_at = calculate_next_run(
            schedule=sub.schedule,
            timezone=user.timezone,
            last_run_at=sub.last_run_at,
            created_at=sub.created_at,
        )
        count += 1

    await db.commit()

    return PauseAllResponse(
        action="resumed",
        affected=count,
    )
