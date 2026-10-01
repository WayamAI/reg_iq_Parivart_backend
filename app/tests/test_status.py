"""
/status reports dependency health without ever leaking a secret.

/health stays the cheap reachability probe; /status is the one allowed to touch the
database, and it must still answer 200 when a dependency is degraded so a caller can tell
"backend up, database down" from "backend unreachable".
"""

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import settings


@pytest.mark.asyncio
async def test_status_reports_app_and_dependency_health(client):
    response = await client.get("/status")

    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "PARIVART Backend API"
    assert body["version"] == "0.1.0"
    assert body["environment"] == settings.APP_ENV
    assert body["database"] == {"status": "up", "error": None}
    assert body["ai"] == {
        "enabled": settings.AI_ENRICHMENT_ENABLED,
        "provider": settings.AI_PROVIDER,
        "model": settings.AI_MODEL,
        "provider_registered": False,
    }


@pytest.mark.asyncio
async def test_status_never_exposes_a_secret(client):
    """The payload must not carry the JWT secret or the database URL."""
    raw = (await client.get("/status")).text

    assert settings.JWT_SECRET not in raw
    assert settings.DATABASE_URL not in raw


@pytest.mark.asyncio
async def test_status_reports_a_dead_database_as_down_not_as_a_500(client, monkeypatch):
    """A database failure is a reported state, never an exception the caller has to parse."""
    import app.main as main

    async def explode(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(main.AsyncSession, "execute", explode)

    response = await client.get("/status")

    assert response.status_code == 200
    database = response.json()["database"]
    assert database["status"] == "down"
    assert "connection refused" in database["error"]
