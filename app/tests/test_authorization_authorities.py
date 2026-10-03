"""
Role enforcement on /regulatory/authorities/*, per
docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md: write operations require
ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER; read stays open to every role.
"""

import pytest

from app.tests.conftest import role_headers


async def _authority_payload():
    import uuid

    return {
        "name": "Authz Test Authority",
        "short_name": f"ATA-{uuid.uuid4().hex[:6]}",
        "jurisdiction": "Testland",
        "country": "Testland",
    }


async def test_admin_can_create_authority(client, auth_headers):
    """auth_headers logs in as admin@asterion.com (ADMIN) -- regression guard that the
    existing, most-used fixture is unaffected by role enforcement."""
    response = await client.post(
        "/api/v1/regulatory/authorities/", json=await _authority_payload(), headers=auth_headers
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("role", ["REGULATORY_MANAGER", "COMPLIANCE_MANAGER"])
async def test_allowed_roles_can_create_authority(client, role):
    headers = await role_headers(client, role)
    response = await client.post(
        "/api/v1/regulatory/authorities/", json=await _authority_payload(), headers=headers
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("role", ["REVIEWER", "ANALYST", "VIEWER"])
async def test_denied_roles_cannot_create_authority(client, role):
    headers = await role_headers(client, role)
    response = await client.post(
        "/api/v1/regulatory/authorities/", json=await _authority_payload(), headers=headers
    )
    assert response.status_code == 403, response.text


async def test_unauthenticated_request_is_401_not_403():
    """Missing credentials must read as 401 (not authenticated), distinct from 403
    (authenticated but not permitted)."""
    import httpx
    from httpx import ASGITransport

    from app.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as anon_client:
        response = await anon_client.post(
            "/api/v1/regulatory/authorities/", json=await _authority_payload()
        )
    assert response.status_code == 401


@pytest.mark.parametrize("role", ["ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"])
async def test_every_role_can_read_authorities(client, role):
    """Read access is unaffected by role -- the matrix proposal's READ class is
    unconditional."""
    headers = await role_headers(client, role)
    response = await client.get("/api/v1/regulatory/authorities/", headers=headers)
    assert response.status_code == 200
