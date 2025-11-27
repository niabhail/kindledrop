from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.delivery import Delivery
    from app.models.user import User


class SubscriptionType(str, Enum):
    RECIPE = "recipe"
    RSS = "rss"


class SubscriptionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    type: Mapped[SubscriptionType] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(255))

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status: Mapped[SubscriptionStatus | None] = mapped_column(
        String(20),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )
