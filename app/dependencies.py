from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User
from app.services.auth import (
    SESSION_COOKIE_NAME,
    decode_session_token,
    get_user_by_id,
    user_count,
)
from app.services.calibre import calibre
from app.services.delivery import DeliveryEngine


async def get_current_user_optional(
    db: Annotated[AsyncSession, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User | None:
    if not session_token:
        return None

    data = decode_session_token(session_token)
    if not data:
        return None

    user_id = data.get("user_id")
    if not user_id:
        return None

    return await get_user_by_id(db, user_id)


async def get_current_user(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


async def require_setup_incomplete(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    count = await user_count(db)
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed",
        )


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_delivery_engine() -> DeliveryEngine:
    """Provide DeliveryEngine instance with configured Calibre wrapper."""
    return DeliveryEngine(calibre=calibre, epub_dir=settings.epub_dir)


DeliveryEngineDep = Annotated[DeliveryEngine, Depends(get_delivery_engine)]
