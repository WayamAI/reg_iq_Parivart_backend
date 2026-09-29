"""
Phase 7 HTTP contract: review and action endpoints.

Covers the full handoff the product depends on -- assessment -> review -> action --
plus authentication, validation, state conflicts and tenant isolation at the edge.
"""

import uuid

from app.db.database import AsyncSessionLocal
from app.models.intelligence import ChangeType, ObligationCategory
from app.tests.conftest import create_authority, create_change


async def _analyze(client, headers, org_id):
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        change_id = await create_change(
            session,
            organization_id=org_id,
            authority=authority,
            summary=(
                "Mandatory electronic labeling requirements for monitoring medical "
                "devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )
    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _register_org(client, slug: str):
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "user_in": {
                "name": "Other Admin",
                "email": f"admin@{slug}.example.com",
                "password": "otherpassword123",
                "role": "ADMIN",
            },
            "org_in": {
                "name": slug.replace("-", " ").title(),
                "slug": slug,
                "industry": "Medical Devices",
                "description": "Second tenant",
            },
        },
    )
    assert res.status_code == 201, res.text
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": f"admin@{slug}.example.com", "password": "otherpassword123"},
    )
    assert login.status_code == 200, login.text
    return res.json()["organization_id"], {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }


# -- the product flow -------------------------------------------------------------------


async def test_assessment_to_review_to_action(client, demo_org, auth_headers):
    """The Phase 7 handoff: a reviewed assessment produces actionable work."""
    assessment = await _analyze(client, auth_headers, demo_org.id)
    assert assessment["items"], "the deterministic engine should match the demo portfolio"

    review_res = await client.post(
        "/api/v1/reviews/",
        json={
            "impact_assessment_id": assessment["id"],
            "decision": "ACCEPT",
            "notes": "Confirmed against our US registrations.",
        },
        headers=auth_headers,
    )
    assert review_res.status_code == 201, review_res.text
    review = review_res.json()
    assert review["previous_state"] == "COMPLETED"
    assert review["new_state"] == "REVIEWED"
    assert review["organization_id"] == demo_org.id

    # The assessment itself now reports the reviewed state.
    fetched = await client.get(
        f"/api/v1/impact/{assessment['id']}", headers=auth_headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "REVIEWED"

    # An action hangs off a real impact item from that assessment.
    item_id = assessment["items"][0]["id"]
    action_res = await client.post(
        "/api/v1/actions/",
        json={
            "title": "Revise electronic labelling for affected devices",
            "description": "Update IFU and submit to the notified body.",
            "impact_item_id": item_id,
            "priority": "HIGH",
        },
        headers=auth_headers,
    )
    assert action_res.status_code == 201, action_res.text
    action = action_res.json()
    assert action["organization_id"] == demo_org.id
    assert action["status"] == "OPEN"
    assert action["impact_item_id"] == item_id
    assert action["completed_at"] is None

    # And it can be driven to completion.
    for nxt in ("IN_PROGRESS", "COMPLETED"):
        res = await client.patch(
            f"/api/v1/actions/{action['id']}/status",
            json={"status": nxt},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
    assert res.json()["completed_at"] is not None


# -- validation and state ---------------------------------------------------------------


async def test_review_of_an_unknown_assessment_is_404(client, demo_org, auth_headers):
    res = await client.post(
        "/api/v1/reviews/",
        json={"impact_assessment_id": str(uuid.uuid4()), "decision": "ACCEPT"},
        headers=auth_headers,
    )
    assert res.status_code == 404, res.text


async def test_invalid_decision_is_422(client, demo_org, auth_headers):
    assessment = await _analyze(client, auth_headers, demo_org.id)
    res = await client.post(
        "/api/v1/reviews/",
        json={"impact_assessment_id": assessment["id"], "decision": "MAYBE"},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text


async def test_reopening_a_completed_action_is_409(client, demo_org, auth_headers):
    created = await client.post(
        "/api/v1/actions/",
        json={"title": "Close me"},
        headers=auth_headers,
    )
    action_id = created.json()["id"]
    await client.patch(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "COMPLETED"},
        headers=auth_headers,
    )
    res = await client.patch(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "OPEN"},
        headers=auth_headers,
    )
    assert res.status_code == 409, res.text


async def test_action_with_an_unknown_impact_item_is_404(client, demo_org, auth_headers):
    res = await client.post(
        "/api/v1/actions/",
        json={"title": "Bad link", "impact_item_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert res.status_code == 404, res.text


async def test_invalid_priority_is_422(client, demo_org, auth_headers):
    res = await client.post(
        "/api/v1/actions/",
        json={"title": "Bad priority", "priority": "URGENT"},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text


async def test_omitted_priority_defaults_to_medium(client, demo_org, auth_headers):
    """
    The served schema advertises ActionCreate.priority as optional with
    `default: MEDIUM`, and the frontend's generated types encode that default rather
    than sending a value of their own. Hold the API to the promise its own OpenAPI
    makes, so the default cannot quietly become null or a validation error.
    """
    res = await client.post(
        "/api/v1/actions/", json={"title": "No priority supplied"}, headers=auth_headers
    )
    assert res.status_code == 201, res.text
    assert res.json()["priority"] == "MEDIUM"


async def test_action_create_schema_marks_only_title_required(client):
    """
    Client types are generated from this schema, so the required set is part of the
    contract. If `priority` ever became required, every generated client that relies
    on the default would start failing validation.
    """
    schema = client._transport.app.openapi()["components"]["schemas"]["ActionCreate"]
    assert schema["required"] == ["title"]
    assert schema["properties"]["priority"]["default"] == "MEDIUM"


async def test_blank_action_title_is_422(client, demo_org, auth_headers):
    res = await client.post(
        "/api/v1/actions/", json={"title": ""}, headers=auth_headers
    )
    assert res.status_code == 422, res.text


# -- authentication ---------------------------------------------------------------------


async def test_review_and_action_endpoints_require_authentication(client, demo_org):
    assert (await client.get("/api/v1/reviews/")).status_code == 401
    assert (await client.get("/api/v1/actions/")).status_code == 401
    assert (
        await client.post("/api/v1/actions/", json={"title": "x"})
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/reviews/",
            json={"impact_assessment_id": "x", "decision": "ACCEPT"},
        )
    ).status_code == 401


# -- tenant isolation -------------------------------------------------------------------


async def test_org_cannot_see_or_touch_another_orgs_reviews_and_actions(
    client, demo_org, auth_headers
):
    org_b_id, headers_b = await _register_org(client, "rival-governance")

    assessment_b = await _analyze(client, headers_b, org_b_id)
    review_b = await client.post(
        "/api/v1/reviews/",
        json={"impact_assessment_id": assessment_b["id"], "decision": "ACCEPT"},
        headers=headers_b,
    )
    assert review_b.status_code == 201, review_b.text
    review_b_id = review_b.json()["id"]

    action_b = await client.post(
        "/api/v1/actions/", json={"title": "B's work"}, headers=headers_b
    )
    assert action_b.status_code == 201, action_b.text
    action_b_id = action_b.json()["id"]

    # Organization A sees none of it, by id or in a listing.
    assert (
        await client.get(f"/api/v1/reviews/{review_b_id}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/actions/{action_b_id}", headers=auth_headers)
    ).status_code == 404

    listed_reviews = await client.get("/api/v1/reviews/", headers=auth_headers)
    assert listed_reviews.status_code == 200
    assert review_b_id not in {r["id"] for r in listed_reviews.json()}

    listed_actions = await client.get("/api/v1/actions/", headers=auth_headers)
    assert listed_actions.status_code == 200
    assert action_b_id not in {a["id"] for a in listed_actions.json()}

    # And cannot mutate it either.
    assert (
        await client.patch(
            f"/api/v1/actions/{action_b_id}",
            json={"title": "hijacked"},
            headers=auth_headers,
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/actions/{action_b_id}/status",
            json={"status": "CANCELLED"},
            headers=auth_headers,
        )
    ).status_code == 404


async def test_org_cannot_review_another_orgs_assessment(client, demo_org, auth_headers):
    org_b_id, headers_b = await _register_org(client, "rival-governance-two")
    assessment_b = await _analyze(client, headers_b, org_b_id)

    res = await client.post(
        "/api/v1/reviews/",
        json={"impact_assessment_id": assessment_b["id"], "decision": "REJECT"},
        headers=auth_headers,
    )
    assert res.status_code == 404, res.text


async def test_reviewer_identity_comes_from_the_token(client, demo_org, auth_headers):
    """
    The reviewer is never taken from the request body. Sending one must not change who
    the review is attributed to.
    """
    assessment = await _analyze(client, auth_headers, demo_org.id)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert me.status_code == 200, me.text

    res = await client.post(
        "/api/v1/reviews/",
        json={
            "impact_assessment_id": assessment["id"],
            "decision": "ACCEPT",
            "reviewer_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["reviewer_id"] == me.json()["id"]


async def test_action_organization_comes_from_the_token(client, demo_org, auth_headers):
    """An organization_id in the body must not place work in another tenant."""
    org_b_id, _ = await _register_org(client, "rival-governance-three")

    res = await client.post(
        "/api/v1/actions/",
        json={"title": "Planted", "organization_id": org_b_id},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["organization_id"] == demo_org.id
