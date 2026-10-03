"""
Role enforcement on /regulatory/sources/*: create/update/delete/run require
ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER; read stays open to every role.
"""

import uuid

import pytest

from app.tests.conftest import role_headers


async def _authority(client, headers) -> str:
    response = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": "Authz Source Test Authority",
            "short_name": f"ASTA-{uuid.uuid4().hex[:6]}",
            "jurisdiction": "Testland",
            "country": "Testland",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("role", ["REVIEWER", "ANALYST", "VIEWER"])
async def test_denied_roles_cannot_create_source(client, auth_headers, role):
    authority_id = await _authority(client, auth_headers)
    headers = await role_headers(client, role)

    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Denied Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["REGULATORY_MANAGER", "COMPLIANCE_MANAGER"])
async def test_allowed_roles_can_create_source(client, auth_headers, role):
    authority_id = await _authority(client, auth_headers)
    headers = await role_headers(client, role)

    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Allowed Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def test_denied_role_cannot_trigger_run(client, auth_headers):
    authority_id = await _authority(client, auth_headers)
    created = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Run Permission Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(
        f"/api/v1/regulatory/sources/{created.json()['id']}/run", headers=viewer
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", ["ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"])
async def test_every_role_can_list_sources(client, role):
    headers = await role_headers(client, role)
    response = await client.get("/api/v1/regulatory/sources/", headers=headers)
    assert response.status_code == 200
