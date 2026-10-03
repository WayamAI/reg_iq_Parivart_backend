"""
The audit trail over HTTP.

Covers the contract a client codes against: the bare-array shape, the filters a
detail screen uses to show one record's history, the parsed payload, and the two
things the endpoint deliberately refuses -- writing, and reading another tenant's
events.
"""

import pytest

from app.services.audit_service import (
    AUDIT_EVENT_TYPES,
    ENTITY_IMPACT_ASSESSMENT,
    EVENT_IMPACT_ASSESSMENT_CREATED,
    EVENT_REVIEW_FILED,
    EVENT_USER_SIGNED_IN,
)


@pytest.mark.asyncio
async def test_signing_in_and_analysing_leaves_a_readable_trail(
    client, auth_headers, seeded_assessment
):
    res = await client.get("/api/v1/audit/", headers=auth_headers)
    assert res.status_code == 200, res.text

    body = res.json()
    # A bare JSON array, like every other list endpoint here -- no envelope.
    assert isinstance(body, list)
    assert len(body) >= 2

    types = {event["event_type"] for event in body}
    assert EVENT_USER_SIGNED_IN in types
    assert EVENT_IMPACT_ASSESSMENT_CREATED in types

    # Newest first.
    timestamps = [event["created_at"] for event in body]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_an_event_names_its_actor_not_just_an_id(
    client, auth_headers, seeded_assessment
):
    """The trail's purpose is 'who', so a reader must not have to resolve a UUID."""
    res = await client.get(
        "/api/v1/audit/",
        params={"event_type": EVENT_USER_SIGNED_IN},
        headers=auth_headers,
    )
    assert res.status_code == 200
    event = res.json()[0]
    assert event["actor_id"]
    assert event["actor_email"] == "admin@asterion.com"
    assert event["actor_name"]


@pytest.mark.asyncio
async def test_entity_filters_answer_the_history_of_one_record(
    client, auth_headers, seeded_assessment
):
    assessment_id = seeded_assessment["assessment_id"]
    res = await client.get(
        "/api/v1/audit/",
        params={"entity_type": ENTITY_IMPACT_ASSESSMENT, "entity_id": assessment_id},
        headers=auth_headers,
    )
    assert res.status_code == 200
    events = res.json()
    assert events
    assert {e["entity_id"] for e in events} == {assessment_id}


@pytest.mark.asyncio
async def test_the_payload_arrives_as_an_object(client, auth_headers, seeded_assessment):
    """Stored as a JSON string in a Text column; a client must not have to parse it."""
    res = await client.get(
        "/api/v1/audit/",
        params={"event_type": EVENT_IMPACT_ASSESSMENT_CREATED},
        headers=auth_headers,
    )
    payload = res.json()[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["regulatory_change_id"] == seeded_assessment["regulatory_change_id"]
    assert payload["analysis_version"] == 1


@pytest.mark.asyncio
async def test_a_filed_decision_shows_both_states(client, auth_headers, seeded_assessment):
    res = await client.post(
        "/api/v1/reviews/",
        json={
            "impact_assessment_id": seeded_assessment["assessment_id"],
            "decision": "ACCEPT",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text

    res = await client.get(
        "/api/v1/audit/", params={"event_type": EVENT_REVIEW_FILED}, headers=auth_headers
    )
    payload = res.json()[0]["payload"]
    assert payload["previous_state"] == "COMPLETED"
    assert payload["new_state"] == "REVIEWED"


@pytest.mark.asyncio
async def test_a_single_event_is_readable_by_id(client, auth_headers, seeded_assessment):
    listed = (await client.get("/api/v1/audit/", headers=auth_headers)).json()[0]
    res = await client.get(f"/api/v1/audit/{listed['id']}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == listed["id"]


@pytest.mark.asyncio
async def test_an_unknown_event_is_404(client, auth_headers, demo_org):
    res = await client.get("/api/v1/audit/does-not-exist", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_the_trail_is_not_writable(client, auth_headers, demo_org):
    """
    No POST, PATCH or DELETE. A trail a caller can write to proves nothing, and one
    a caller can edit is not a trail.
    """
    listed = await client.get("/api/v1/audit/", headers=auth_headers)
    assert listed.status_code == 200

    # httpx's delete() takes no body, so the write attempts are issued through the
    # generic request() rather than the per-verb helpers.
    for method, url in (
        ("POST", "/api/v1/audit/"),
        ("PATCH", "/api/v1/audit/some-id"),
        ("DELETE", "/api/v1/audit/some-id"),
    ):
        res = await client.request(method, url, headers=auth_headers)
        assert res.status_code == 405, f"{method} {url} -> {res.status_code}"


@pytest.mark.asyncio
async def test_the_trail_requires_authentication(client, demo_org):
    assert (await client.get("/api/v1/audit/")).status_code == 401


@pytest.mark.asyncio
async def test_the_served_vocabulary_matches_what_the_services_write(
    client, auth_headers, demo_org
):
    res = await client.get("/api/v1/audit/event-types", headers=auth_headers)
    assert res.status_code == 200
    assert set(res.json()["event_types"]) == set(AUDIT_EVENT_TYPES)


@pytest.mark.asyncio
async def test_paging_is_skip_and_limit_with_no_total(
    client, auth_headers, seeded_assessment
):
    res = await client.get(
        "/api/v1/audit/", params={"skip": 0, "limit": 1}, headers=auth_headers
    )
    assert res.status_code == 200
    assert len(res.json()) == 1
    # No envelope means no total; that is the contract, not an omission.
    assert isinstance(res.json(), list)


@pytest.mark.asyncio
async def test_one_tenant_cannot_read_another_tenants_trail(
    client, auth_headers, seeded_assessment
):
    """
    The trail is the most sensitive read in the product -- it says who did what --
    so the tenant boundary is asserted over HTTP, not only in the service.

    A second tenant sees only its own sign-in, and an event id belonging to the
    first tenant reads as missing rather than forbidden, so the response never
    confirms that the id exists somewhere else.
    """
    from app.tests.test_impact_isolation import _register_org

    mine = (await client.get("/api/v1/audit/", headers=auth_headers)).json()
    assert len(mine) >= 2

    _, headers_b = await _register_org(client, "rival-devices-audit")

    theirs = await client.get("/api/v1/audit/", headers=headers_b)
    assert theirs.status_code == 200
    # Their own sign-in, and nothing of ours.
    assert {e["event_type"] for e in theirs.json()} == {EVENT_USER_SIGNED_IN}
    assert {e["id"] for e in theirs.json()}.isdisjoint({e["id"] for e in mine})

    leaked = await client.get(f"/api/v1/audit/{mine[0]['id']}", headers=headers_b)
    assert leaked.status_code == 404
