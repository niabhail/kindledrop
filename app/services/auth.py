from datetime import datetime
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeTimedSerializer(settings.secret_key)

SESSION_COOKIE_NAME = "kindledrop_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id, "created": datetime.utcnow().isoformat()})


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    user = await get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> User:
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def user_count(db: AsyncSession) -> int:
    result = await db.execute(select(User))
    return len(result.scalars().all())
