"""Tests for SMTP service."""

from pathlib import Path

import pytest

from app.services.smtp import (
    MAX_FILE_SIZE,
    SMTPConfig,
    SMTPError,
    SMTPSizeError,
    send_kindle_email,
    verify_smtp_connection,
)


class TestSMTPConfig:
    """Test SMTPConfig dataclass."""

    def test_from_dict_basic(self):
        config = SMTPConfig.from_dict({
            "host": "smtp.test.com",
            "port": 587,
            "username": "user",
            "password": "pass",
            "from_email": "from@test.com",
        })
        assert config.host == "smtp.test.com"
        assert config.port == 587
        assert config.username == "user"
        assert config.password == "pass"
        assert config.from_email == "from@test.com"
        assert config.use_tls is True  # default

    def test_from_dict_with_tls_false(self):
        config = SMTPConfig.from_dict({
            "host": "smtp.test.com",
            "port": 25,
            "username": "user",
            "password": "pass",
            "from_email": "from@test.com",
            "use_tls": False,
        })
        assert config.use_tls is False

    def test_from_dict_default_port(self):
        config = SMTPConfig.from_dict({
            "host": "smtp.test.com",
            "username": "user",
            "password": "pass",
            "from_email": "from@test.com",
        })
        assert config.port == 587


class TestSendKindleEmail:
    """Test send_kindle_email function."""

    @pytest.fixture
    def config(self):
        return SMTPConfig(
            host="smtp.test.com",
            port=587,
            username="user",
            password="pass",
            from_email="from@test.com",
        )

    @pytest.fixture
    def small_epub(self, tmp_path):
        """Create a small test EPUB file."""
        epub = tmp_path / "test.epub"
        epub.write_bytes(b"PK" + b"\x00" * 1000)
        return epub

    @pytest.fixture
    def large_epub(self, tmp_path):
        """Create a file larger than MAX_FILE_SIZE."""
        epub = tmp_path / "large.epub"
        epub.write_bytes(b"\x00" * (MAX_FILE_SIZE + 1000))
        return epub

    async def test_send_success(self, config, small_epub, mock_smtp):
        """Test successful email send."""
        await send_kindle_email(
            config=config,
            to_email="kindle@kindle.com",
            subject="Test Subject",
            epub_path=small_epub,
        )
        mock_smtp.assert_called_once()

    async def test_send_file_not_found(self, config):
        """Test error when EPUB file doesn't exist."""
        with pytest.raises(SMTPError, match="EPUB file not found"):
            await send_kindle_email(
                config=config,
                to_email="kindle@kindle.com",
                subject="Test",
                epub_path=Path("/nonexistent/file.epub"),
            )

    async def test_send_file_too_large(self, config, large_epub):
        """Test error when file exceeds size limit."""
        with pytest.raises(SMTPSizeError, match="too large"):
            await send_kindle_email(
                config=config,
                to_email="kindle@kindle.com",
                subject="Test",
                epub_path=large_epub,
            )


class TestVerifySMTPConnection:
    """Test verify_smtp_connection function."""

    @pytest.fixture
    def config(self):
        return SMTPConfig(
            host="smtp.test.com",
            port=587,
            username="user",
            password="pass",
            from_email="from@test.com",
        )

    async def test_connection_success(self, config, mock_smtp_connection):
        """Test successful connection test."""
        result = await verify_smtp_connection(config)
        assert result is True
