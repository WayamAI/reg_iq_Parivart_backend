"""
The demo login bypass: any email, any password -- and only in development.

The bypass is an authentication bypass, so the tests that matter most here are the ones
asserting it stays OFF: off by default, and inert in a non-development APP_ENV even when
the flag is set.
"""

import pytest

from app.core.config import settings


async def _login(client, email, password):
    return await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )


@pytest.fixture
def demo_auth_on(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_AUTH_ALLOW_ANY", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")


# --- the bypass is off by default ------------------------------------------------------

@pytest.mark.asyncio
async def test_default_configuration_leaves_the_bypass_off(demo_org):
    assert settings.DEMO_AUTH_ALLOW_ANY is False
    assert settings.demo_auth_active is False


def test_test_environment_pins_bypass_off_in_os_environ():
    """conftest must pin DEMO_AUTH_ALLOW_ANY=false so tests stay hermetic from local .env files."""
    import os
    assert os.environ.get("DEMO_AUTH_ALLOW_ANY") == "false"


@pytest.mark.asyncio
async def test_wrong_password_is_rejected_by_default(client, demo_org):
    response = await _login(client, "admin@asterion.com", "not-the-password")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unknown_email_is_rejected_by_default(client, demo_org):
    response = await _login(client, "nobody@example.com", "anything")
    assert response.status_code == 401


# --- a production APP_ENV disarms it ---------------------------------------------------

@pytest.mark.asyncio
async def test_flag_alone_does_not_enable_the_bypass_in_production(
    client, demo_org, monkeypatch
):
    """The flag travelling into a production config must do nothing."""
    monkeypatch.setattr(settings, "DEMO_AUTH_ALLOW_ANY", True)
    monkeypatch.setattr(settings, "APP_ENV", "production")

    assert settings.demo_auth_active is False
    assert (await _login(client, "nobody@example.com", "anything")).status_code == 401
    assert (await _login(client, "admin@asterion.com", "wrong")).status_code == 401


# --- enabled: any email, any password --------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_email_is_provisioned_into_the_demo_organization(
    client, demo_org, demo_auth_on
):
    response = await _login(client, "whoever@example.com", "whatever")

    assert response.status_code == 200
    token = response.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "whoever@example.com"
    assert me.json()["organization_id"] == demo_org.id


@pytest.mark.asyncio
async def test_known_email_accepts_any_password(client, demo_org, demo_auth_on):
    response = await _login(client, "admin@asterion.com", "definitely-wrong")

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "admin@asterion.com"


@pytest.mark.asyncio
async def test_repeated_demo_login_reuses_the_same_user(client, demo_org, demo_auth_on):
    first = await _login(client, "repeat@example.com", "a")
    second = await _login(client, "repeat@example.com", "b")

    assert first.status_code == second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]


@pytest.mark.asyncio
async def test_inactive_user_is_still_refused(client, demo_org, demo_auth_on):
    """The bypass skips the password check, not every other gate."""
    from sqlalchemy import update

    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(User).where(User.email == "analyst@asterion.com").values(is_active=False)
        )
        await session.commit()

    response = await _login(client, "analyst@asterion.com", "anything")
    assert response.status_code == 400
