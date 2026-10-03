"""
Role enforcement on document upload/processing:
ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER only (ANALYST excluded per the matrix
proposal's resolved policy decision -- see
docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md). Read endpoints stay open to every role.
"""

import io
import uuid

import pytest

from app.tests.conftest import role_headers


async def _authority_and_source(client, headers):
    authority = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": "Authz Doc Test Authority",
            "short_name": f"ADTA-{uuid.uuid4().hex[:6]}",
            "jurisdiction": "Testland",
            "country": "Testland",
        },
        headers=headers,
    )
    assert authority.status_code == 201, authority.text
    source = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority.json()["id"],
            "name": "Authz Doc Test Source",
            "source_type": "DOCUMENT",
            "connector_type": "DOCUMENT",
            "enabled": True,
        },
        headers=headers,
    )
    assert source.status_code == 201, source.text
    return authority.json()["id"], source.json()["id"]


@pytest.mark.parametrize("role", ["ANALYST", "REVIEWER", "VIEWER"])
async def test_denied_roles_cannot_upload_a_document(client, auth_headers, role):
    authority_id, source_id = await _authority_and_source(client, auth_headers)
    headers = await role_headers(client, role)

    response = await client.post(
        "/api/v1/regulatory/documents/upload",
        files={"file": ("notice.txt", io.BytesIO(b"A notice."), "text/plain")},
        data={"title": "Denied Upload", "authority_id": authority_id, "source_id": source_id},
        headers=headers,
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["REGULATORY_MANAGER", "COMPLIANCE_MANAGER"])
async def test_allowed_roles_can_upload_a_document(client, auth_headers, role):
    authority_id, source_id = await _authority_and_source(client, auth_headers)
    headers = await role_headers(client, role)

    response = await client.post(
        "/api/v1/regulatory/documents/upload",
        files={"file": ("notice.txt", io.BytesIO(b"A notice for allowed roles."), "text/plain")},
        data={"title": "Allowed Upload", "authority_id": authority_id, "source_id": source_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def test_every_role_can_read_document_status_and_list(client, auth_headers):
    authority_id, source_id = await _authority_and_source(client, auth_headers)
    uploaded = await client.post(
        "/api/v1/regulatory/documents/upload",
        files={"file": ("notice.txt", io.BytesIO(b"Read-access test."), "text/plain")},
        data={"title": "Read Test", "authority_id": authority_id, "source_id": source_id},
        headers=auth_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document_id"]

    for role in ("ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"):
        if role == "ADMIN":
            headers = auth_headers
        else:
            headers = await role_headers(client, role)
        listed = await client.get("/api/v1/regulatory/documents/", headers=headers)
        assert listed.status_code == 200, (role, listed.text)
