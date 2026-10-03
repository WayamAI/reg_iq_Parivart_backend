"""
Role enforcement on actions and evidence:
ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER/REVIEWER may create/transition actions and
upload evidence. ANALYST/VIEWER may not.
"""

import io

import pytest

from app.tests.conftest import role_headers, teammate_headers


@pytest.mark.parametrize("role", ["ANALYST", "VIEWER"])
async def test_denied_roles_cannot_create_an_action(client, role):
    headers = await role_headers(client, role)
    response = await client.post(
        "/api/v1/actions/", json={"title": "Denied Action"}, headers=headers
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER"])
async def test_allowed_roles_can_create_an_action(client, demo_org, role):
    headers = await teammate_headers(client, demo_org.id, role)
    response = await client.post(
        "/api/v1/actions/", json={"title": "Allowed Action"}, headers=headers
    )
    assert response.status_code == 201, response.text


async def test_every_role_can_list_actions(client, demo_org):
    for role in ("ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"):
        headers = await teammate_headers(client, demo_org.id, role)
        response = await client.get("/api/v1/actions/", headers=headers)
        assert response.status_code == 200, role


async def test_denied_role_cannot_upload_evidence(client, demo_org):
    owner_headers = await teammate_headers(client, demo_org.id, "ADMIN")
    created = await client.post(
        "/api/v1/actions/", json={"title": "Evidence Target Action"}, headers=owner_headers
    )
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(
        "/api/v1/evidence/upload",
        files={"file": ("proof.txt", io.BytesIO(b"proof"), "text/plain")},
        data={"action_id": action_id},
        headers=viewer,
    )
    assert response.status_code == 403


async def test_allowed_role_can_upload_evidence(client, demo_org):
    owner_headers = await teammate_headers(client, demo_org.id, "ADMIN")
    created = await client.post(
        "/api/v1/actions/", json={"title": "Evidence Target Action 2"}, headers=owner_headers
    )
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]

    reviewer = await teammate_headers(client, demo_org.id, "REVIEWER")
    response = await client.post(
        "/api/v1/evidence/upload",
        files={"file": ("proof.txt", io.BytesIO(b"proof"), "text/plain")},
        data={"action_id": action_id},
        headers=reviewer,
    )
    assert response.status_code == 201, response.text


async def test_every_role_can_list_evidence(client, demo_org):
    for role in ("ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"):
        headers = await teammate_headers(client, demo_org.id, role)
        response = await client.get("/api/v1/evidence/", headers=headers)
        assert response.status_code == 200, role
