import asyncio
import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment before importing app
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.database import get_db
from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client for API tests WITHOUT authentication.
    Use authed_client fixture for authenticated requests.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def authed_client(
    db_session: AsyncSession, test_user
) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client for API tests WITH authentication.
    Automatically injects test_user as the current user.
    """
    from app.dependencies import get_current_user

    async def override_get_db():
        yield db_session

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def mock_calibre():
    with patch("app.services.calibre.calibre") as mock:
        mock.list_builtin_recipes = AsyncMock(return_value=[])
        mock.verify_installation = AsyncMock(return_value="calibre 7.0")
        yield mock


@pytest.fixture
def mock_smtp():
    """Mock SMTP sending for delivery tests."""
    with patch("app.services.smtp.aiosmtplib.send") as mock:
        mock.return_value = None
        yield mock


@pytest.fixture
def mock_smtp_connection():
    """Mock SMTP connection test."""
    with patch("app.services.smtp.aiosmtplib.SMTP") as mock:
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_instance.login = AsyncMock(return_value=None)
        mock.return_value = mock_instance
        yield mock


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """Create a test user with SMTP config."""
    from app.models import User

    # Use a pre-computed bcrypt hash to avoid passlib/bcrypt compatibility issues in tests
    # This is equivalent to hash_password("testpassword123") but computed ahead of time
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash="$2b$12$test.hash.for.testing.purposes.only",
        kindle_email="test@kindle.com",
        timezone="UTC",
        smtp_config={
            "host": "smtp.test.com",
            "port": 587,
            "username": "smtp_user",
            "password": "smtp_pass",
            "from_email": "from@test.com",
            "use_tls": True,
        },
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_subscription(db_session: AsyncSession, test_user):
    """Create a test subscription."""
    from app.models import Subscription, SubscriptionType

    subscription = Subscription(
        user_id=test_user.id,
        type=SubscriptionType.RECIPE,
        source="the_guardian",
        name="The Guardian",
        schedule={"type": "daily", "time": "07:00"},
        settings={"max_articles": 25, "oldest_days": 7, "include_images": True},
    )
    db_session.add(subscription)
    await db_session.flush()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
def mock_calibre_fetch(tmp_path):
    """Mock Calibre fetch operations that create real files."""
    from pathlib import Path

    # Create a fake EPUB file
    fake_epub = tmp_path / "test.epub"
    fake_epub.write_bytes(b"PK" + b"\x00" * 1000)  # Minimal ZIP header + content

    # Note: These are instance methods, so 'self' is passed as first arg
    async def mock_fetch_recipe(self, recipe_name, output_path, **kwargs):
        # Copy fake epub to output path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fake_epub.read_bytes())
        return Path(output_path)

    async def mock_fetch_rss(self, feed_url, title, output_path, **kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fake_epub.read_bytes())
        return Path(output_path)

    with patch("app.services.calibre.CalibreWrapper.fetch_recipe", new=mock_fetch_recipe):
        with patch("app.services.calibre.CalibreWrapper.fetch_rss", new=mock_fetch_rss):
            yield {"epub_path": fake_epub}
