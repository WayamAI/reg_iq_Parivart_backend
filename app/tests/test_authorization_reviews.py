"""
Role enforcement on filing a review decision: ADMIN/COMPLIANCE_MANAGER/REVIEWER only.
"""

import pytest

from app.tests.conftest import role_headers, teammate_headers


@pytest.mark.parametrize("role", ["REGULATORY_MANAGER", "ANALYST", "VIEWER"])
async def test_denied_roles_cannot_file_a_review(client, seeded_assessment, role):
    headers = await role_headers(client, role)
    response = await client.post(
        "/api/v1/reviews/",
        json={
            "impact_assessment_id": seeded_assessment["assessment_id"],
            "decision": "ACCEPT",
            "notes": "Should be denied.",
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("role", ["COMPLIANCE_MANAGER", "REVIEWER"])
async def test_allowed_roles_within_the_same_org_can_file_a_review(
    client, demo_org, seeded_assessment, role
):
    headers = await teammate_headers(client, demo_org.id, role)
    response = await client.post(
        "/api/v1/reviews/",
        json={
            "impact_assessment_id": seeded_assessment["assessment_id"],
            "decision": "ACCEPT",
            "notes": "Allowed role, same tenant.",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def test_every_role_can_list_reviews(client, seeded_assessment, auth_headers):
    for role in ("ADMIN", "REGULATORY_MANAGER", "COMPLIANCE_MANAGER", "REVIEWER", "ANALYST", "VIEWER"):
        headers = auth_headers if role == "ADMIN" else await role_headers(client, role)
        response = await client.get("/api/v1/reviews/", headers=headers)
        assert response.status_code == 200, role
