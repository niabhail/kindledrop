from datetime import datetime, timedelta
from typing import Any
import secrets

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
    # bcrypt has a 72-byte limit; truncate to avoid errors with bcrypt 4.0+
    return pwd_context.hash(password[:72])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password[:72], hashed_password)


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


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Get user by email address."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_password_reset_token(db: AsyncSession, email: str) -> str | None:
    """Create a password reset token for a user.

    Returns the reset token if user exists, None otherwise.
    """
    user = await get_user_by_email(db, email)
    if not user:
        return None

    # Generate secure random token
    token = secrets.token_urlsafe(32)

    # Set token and expiration (1 hour)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)

    await db.commit()
    return token


async def verify_reset_token(db: AsyncSession, token: str) -> User | None:
    """Verify a password reset token and return the user if valid.

    Returns None if token is invalid or expired.
    """
    result = await db.execute(select(User).where(User.reset_token == token))
    user = result.scalar_one_or_none()

    if not user:
        return None

    # Check if token is expired
    if not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        return None

    return user


async def reset_password_with_token(
    db: AsyncSession, token: str, new_password: str
) -> bool:
    """Reset a user's password using a valid reset token.

    Returns True if successful, False otherwise.
    """
    user = await verify_reset_token(db, token)
    if not user:
        return False

    # Update password and clear reset token
    user.password_hash = hash_password(new_password)
    user.reset_token = None
    user.reset_token_expires = None

    await db.commit()
    return True
