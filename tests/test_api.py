import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_setup_page_redirects_when_no_users(client: AsyncClient):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/setup"


@pytest.mark.asyncio
async def test_setup_shows_form_when_no_users(client: AsyncClient):
    response = await client.get("/setup")
    assert response.status_code == 200
    assert b"Create your admin account" in response.content


@pytest.mark.asyncio
async def test_login_with_invalid_credentials(client: AsyncClient):
    response = await client.post(
        "/login",
        data={"username": "nonexistent", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_auth_me_requires_auth(client: AsyncClient):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
