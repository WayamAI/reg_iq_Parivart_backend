"""
Role enforcement on impact-assessment triggers:
ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER only (ANALYST excluded per the matrix
proposal's resolved policy decision). Read endpoints stay open to every role.
"""

import pytest

from app.tests.conftest import role_headers


@pytest.mark.parametrize("role", ["ANALYST", "REVIEWER", "VIEWER"])
async def test_denied_roles_cannot_trigger_analysis(client, seeded_assessment, role):
    headers = await role_headers(client, role)
    response = await client.post(
        "/api/v1/impact/analyze",
        json={
            "regulatory_change_id": seeded_assessment["regulatory_change_id"],
            "force_reanalyze": True,
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"])
async def test_every_role_can_list_assessments(client, seeded_assessment, auth_headers, role):
    headers = auth_headers if role == "ADMIN" else await role_headers(client, role)
    response = await client.get("/api/v1/impact/", headers=headers)
    assert response.status_code == 200


async def test_denied_role_cannot_reanalyze(client, seeded_assessment):
    headers = await role_headers(client, "VIEWER")
    response = await client.post(
        f"/api/v1/impact/{seeded_assessment['assessment_id']}/reanalyze", headers=headers
    )
    assert response.status_code == 403
