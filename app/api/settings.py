"""
Settings API - manage user settings including SMTP configuration.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.dependencies import CurrentUser, DbSession
from app.services.smtp import (
    SMTPAuthError,
    SMTPConfig,
    SMTPConnectionError,
    SMTPError,
    verify_smtp_connection,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SMTPSettings(BaseModel):
    """SMTP server configuration."""

    host: str
    port: int = 587
    username: str
    password: str
    from_email: EmailStr
    use_tls: bool = True


class UserSettingsResponse(BaseModel):
    """Response model for user settings."""

    username: str
    email: str
    kindle_email: str | None
    timezone: str
    smtp_configured: bool
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_from_email: str | None = None


class UserSettingsUpdate(BaseModel):
    """Request model for updating user settings."""

    kindle_email: EmailStr | None = None
    timezone: str | None = None
    smtp: SMTPSettings | None = None


class TestEmailResponse(BaseModel):
    """Response model for test email."""

    success: bool
    message: str


@router.get("")
async def get_settings(
    user: CurrentUser,
) -> UserSettingsResponse:
    """Get current user settings."""
    smtp = user.smtp_config or {}

    return UserSettingsResponse(
        username=user.username,
        email=user.email,
        kindle_email=user.kindle_email,
        timezone=user.timezone,
        smtp_configured=bool(user.smtp_config),
        smtp_host=smtp.get("host"),
        smtp_port=smtp.get("port"),
        smtp_username=smtp.get("username"),
        smtp_from_email=smtp.get("from_email"),
    )


@router.put("")
async def update_settings(
    request: UserSettingsUpdate,
    user: CurrentUser,
    db: DbSession,
) -> UserSettingsResponse:
    """Update user settings."""
    if request.kindle_email is not None:
        user.kindle_email = request.kindle_email

    if request.timezone is not None:
        user.timezone = request.timezone

    if request.smtp is not None:
        user.smtp_config = {
            "host": request.smtp.host,
            "port": request.smtp.port,
            "username": request.smtp.username,
            "password": request.smtp.password,
            "from_email": request.smtp.from_email,
            "use_tls": request.smtp.use_tls,
        }

    await db.flush()
    await db.refresh(user)

    smtp = user.smtp_config or {}
    return UserSettingsResponse(
        username=user.username,
        email=user.email,
        kindle_email=user.kindle_email,
        timezone=user.timezone,
        smtp_configured=bool(user.smtp_config),
        smtp_host=smtp.get("host"),
        smtp_port=smtp.get("port"),
        smtp_username=smtp.get("username"),
        smtp_from_email=smtp.get("from_email"),
    )


@router.post("/test-email")
async def test_email(
    user: CurrentUser,
) -> TestEmailResponse:
    """
    Test SMTP connection and authentication.

    Does not send an actual email, just validates credentials.
    """
    if not user.smtp_config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP settings not configured",
        )

    try:
        config = SMTPConfig.from_dict(user.smtp_config)
        await verify_smtp_connection(config)
        return TestEmailResponse(
            success=True,
            message=f"Successfully connected to {config.host}:{config.port}",
        )

    except SMTPAuthError as e:
        return TestEmailResponse(
            success=False,
            message=f"Authentication failed: {e}",
        )

    except SMTPConnectionError as e:
        return TestEmailResponse(
            success=False,
            message=f"Connection failed: {e}",
        )

    except SMTPError as e:
        return TestEmailResponse(
            success=False,
            message=f"SMTP error: {e}",
        )
