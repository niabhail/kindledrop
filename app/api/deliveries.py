"""
Deliveries API - delivery history and retry functionality.
"""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUser, DbSession, DeliveryEngineDep
from app.models import Delivery, DeliveryStatus, Subscription

router = APIRouter(prefix="/api/deliveries", tags=["deliveries"])


class DeliveryResponse(BaseModel):
    """Response model for delivery records."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    subscription_id: int
    subscription_name: str
    status: str
    scheduled_at: str
    started_at: str | None
    completed_at: str | None
    file_size_bytes: int | None
    article_count: int | None
    error_stage: str | None
    error_message: str | None
    created_at: str


def _delivery_to_response(delivery: Delivery, subscription_name: str) -> DeliveryResponse:
    """Convert Delivery model to response."""
    return DeliveryResponse(
        id=delivery.id,
        subscription_id=delivery.subscription_id,
        subscription_name=subscription_name,
        status=delivery.status.value if isinstance(delivery.status, DeliveryStatus) else delivery.status,
        scheduled_at=delivery.scheduled_at.isoformat(),
        started_at=delivery.started_at.isoformat() if delivery.started_at else None,
        completed_at=delivery.completed_at.isoformat() if delivery.completed_at else None,
        file_size_bytes=delivery.file_size_bytes,
        article_count=delivery.article_count,
        error_stage=delivery.error_stage,
        error_message=delivery.error_message,
        created_at=delivery.created_at.isoformat(),
    )


@router.get("")
async def list_deliveries(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(20, le=100, ge=1),
    offset: int = Query(0, ge=0),
) -> list[DeliveryResponse]:
    """
    List recent deliveries for the current user.

    Ordered by creation time, most recent first.
    """
    result = await db.execute(
        select(Delivery)
        .options(selectinload(Delivery.subscription))
        .where(Delivery.user_id == user.id)
        .order_by(Delivery.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    deliveries = result.scalars().all()

    return [
        _delivery_to_response(d, d.subscription.name if d.subscription else "Deleted")
        for d in deliveries
    ]


@router.get("/{delivery_id}")
async def get_delivery(
    delivery_id: int,
    user: CurrentUser,
    db: DbSession,
) -> DeliveryResponse:
    """Get details of a specific delivery."""
    result = await db.execute(
        select(Delivery)
        .options(selectinload(Delivery.subscription))
        .where(
            Delivery.id == delivery_id,
            Delivery.user_id == user.id,
        )
    )
    delivery = result.scalar_one_or_none()

    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        )

    return _delivery_to_response(
        delivery,
        delivery.subscription.name if delivery.subscription else "Deleted",
    )


@router.post("/{delivery_id}/retry")
async def retry_delivery(
    delivery_id: int,
    user: CurrentUser,
    db: DbSession,
    engine: DeliveryEngineDep,
) -> DeliveryResponse:
    """
    Retry a failed delivery.

    Creates a new delivery attempt for the same subscription.
    Only failed deliveries can be retried.
    """
    # Get the original delivery
    result = await db.execute(
        select(Delivery)
        .options(selectinload(Delivery.subscription))
        .where(
            Delivery.id == delivery_id,
            Delivery.user_id == user.id,
        )
    )
    delivery = result.scalar_one_or_none()

    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        )

    if delivery.status != DeliveryStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed deliveries can be retried",
        )

    if not delivery.subscription:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription has been deleted",
        )

    # Get the full subscription (may need it for settings)
    result = await db.execute(
        select(Subscription).where(Subscription.id == delivery.subscription_id)
    )
    subscription = result.scalar_one()

    # Execute new delivery
    delivery_result = await engine.execute(
        db=db,
        subscription=subscription,
        user=user,
    )

    # Get the new delivery for response
    result = await db.execute(
        select(Delivery)
        .options(selectinload(Delivery.subscription))
        .where(Delivery.id == delivery_result.delivery_id)
    )
    new_delivery = result.scalar_one()

    return _delivery_to_response(new_delivery, subscription.name)
