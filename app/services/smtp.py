"""
SMTP service for sending EPUBs to Kindle via email.

Uses aiosmtplib for async email sending with MIME attachments.
"""

import logging
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib

logger = logging.getLogger(__name__)

# 11MB limit - Mailjet allows 15MB total, base64 adds ~33% overhead
# This gives us ~11MB effective attachment size
MAX_FILE_SIZE = 11 * 1024 * 1024


class SMTPError(Exception):
    """Base exception for SMTP errors with actionable messages."""

    pass


class SMTPConnectionError(SMTPError):
    """Failed to connect to SMTP server."""

    pass


class SMTPAuthError(SMTPError):
    """SMTP authentication failed."""

    pass


class SMTPSizeError(SMTPError):
    """Attachment exceeds size limit."""

    pass


@dataclass
class SMTPConfig:
    """SMTP server configuration."""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "SMTPConfig":
        """Create SMTPConfig from dictionary (e.g., User.smtp_config JSON)."""
        return cls(
            host=data["host"],
            port=data.get("port", 587),
            username=data["username"],
            password=data["password"],
            from_email=data["from_email"],
            use_tls=data.get("use_tls", True),
        )


async def send_kindle_email(
    config: SMTPConfig,
    to_email: str,
    subject: str,
    epub_path: Path,
    display_name: str | None = None,
) -> None:
    """
    Send EPUB file to Kindle via email.

    Args:
        config: SMTP server configuration
        to_email: Recipient email (Kindle address)
        subject: Email subject line
        epub_path: Path to EPUB file to attach
        display_name: Human-readable name for the attachment (becomes Kindle title)

    Raises:
        SMTPSizeError: If file exceeds 7MB limit
        SMTPConnectionError: If cannot connect to SMTP server
        SMTPAuthError: If authentication fails
        SMTPError: For other sending errors
    """
    # Validate file exists
    if not epub_path.exists():
        raise SMTPError(f"EPUB file not found: {epub_path}")

    # Validate file size
    file_size = epub_path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise SMTPSizeError(
            f"File too large: {file_size / 1024 / 1024:.1f}MB exceeds 11MB limit"
        )

    # Build email message
    message = MIMEMultipart()
    message["From"] = config.from_email
    message["To"] = to_email
    message["Subject"] = subject

    # Add a simple body (Kindle ignores this but it's good practice)
    body = MIMEText(
        f"Your Kindledrop delivery: {epub_path.name}\n\n"
        "This email was sent by Kindledrop.",
        "plain",
    )
    message.attach(body)

    # Attach EPUB file with human-readable filename for Kindle title
    attachment_filename = f"{display_name}.epub" if display_name else epub_path.name
    with open(epub_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="epub+zip")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=attachment_filename,
        )
        message.attach(attachment)

    logger.info(
        f"Sending email to {to_email} via {config.host}:{config.port} "
        f"({file_size / 1024:.1f} KB)"
    )

    try:
        await aiosmtplib.send(
            message,
            hostname=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            start_tls=config.use_tls,
        )
        logger.info(f"Email sent successfully to {to_email}")

    except aiosmtplib.SMTPAuthenticationError as e:
        raise SMTPAuthError(
            f"SMTP authentication failed for {config.username}@{config.host}: {e}"
        )

    except aiosmtplib.SMTPConnectError as e:
        raise SMTPConnectionError(
            f"Cannot connect to SMTP server {config.host}:{config.port}: {e}"
        )

    except aiosmtplib.SMTPException as e:
        raise SMTPError(f"Failed to send email: {e}")


async def verify_smtp_connection(config: SMTPConfig) -> bool:
    """
    Verify SMTP connection and authentication.

    Args:
        config: SMTP server configuration

    Returns:
        True if connection successful

    Raises:
        SMTPConnectionError: If cannot connect
        SMTPAuthError: If authentication fails
    """
    logger.info(f"Testing SMTP connection to {config.host}:{config.port}")

    try:
        async with aiosmtplib.SMTP(
            hostname=config.host,
            port=config.port,
            start_tls=config.use_tls,
        ) as smtp:
            await smtp.login(config.username, config.password)
            logger.info("SMTP connection test successful")
            return True

    except aiosmtplib.SMTPAuthenticationError as e:
        raise SMTPAuthError(
            f"SMTP authentication failed for {config.username}@{config.host}: {e}"
        )

    except aiosmtplib.SMTPConnectError as e:
        raise SMTPConnectionError(
            f"Cannot connect to SMTP server {config.host}:{config.port}: {e}"
        )

    except aiosmtplib.SMTPException as e:
        raise SMTPError(f"SMTP test failed: {e}")
