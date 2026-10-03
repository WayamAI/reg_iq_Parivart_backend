"""
Regulatory changes and obligations over HTTP.

The endpoints are small; the tenancy is the part worth testing. Neither table has
an organization_id, so ownership is established by joining the parent document. A
missing join here would expose every tenant's extracted regulatory intelligence to
every other tenant, and would not show up as a failure anywhere else.
"""

import pytest

from app.db.database import AsyncSessionLocal
from app.models.intelligence import ChangeType, ObligationCategory
from app.tests.conftest import create_authority, create_change


@pytest.mark.asyncio
async def test_a_change_is_listable_and_readable(
    client, auth_headers, seeded_assessment
):
    change_id = seeded_assessment["regulatory_change_id"]

    listed = await client.get("/api/v1/regulatory/changes/", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    # A bare JSON array, like every other list endpoint here.
    assert isinstance(listed.json(), list)
    assert change_id in {c["id"] for c in listed.json()}

    one = await client.get(
        f"/api/v1/regulatory/changes/{change_id}", headers=auth_headers
    )
    assert one.status_code == 200
    body = one.json()
    assert body["id"] == change_id
    assert body["change_type"] == "LABELING_CHANGE"
    assert body["summary"]
    # Numeric(3,2) must serialise as a JSON number, not a string.
    assert isinstance(body["confidence"], float)


@pytest.mark.asyncio
async def test_an_assessments_change_id_now_resolves(
    client, auth_headers, seeded_assessment
):
    """
    The gap this router exists to close: an assessment referenced a change that no
    endpoint could resolve, so the UI dead-ended on an id.
    """
    assessment = await client.get(
        f"/api/v1/impact/{seeded_assessment['assessment_id']}", headers=auth_headers
    )
    assert assessment.status_code == 200
    change_id = assessment.json()["regulatory_change_id"]

    res = await client.get(
        f"/api/v1/regulatory/changes/{change_id}", headers=auth_headers
    )
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_a_changes_obligations_are_reachable_from_it(
    client, auth_headers, seeded_assessment
):
    change_id = seeded_assessment["regulatory_change_id"]
    res = await client.get(
        f"/api/v1/regulatory/changes/{change_id}/obligations", headers=auth_headers
    )
    assert res.status_code == 200
    obligations = res.json()
    assert len(obligations) == 1
    assert obligations[0]["category"] == "LABELING"
    assert obligations[0]["change_id"] == change_id
    assert obligations[0]["text"]


@pytest.mark.asyncio
async def test_obligations_are_listable_and_filterable(
    client, auth_headers, seeded_assessment
):
    change_id = seeded_assessment["regulatory_change_id"]

    listed = await client.get("/api/v1/regulatory/obligations/", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    by_change = await client.get(
        "/api/v1/regulatory/obligations/",
        params={"regulatory_change_id": change_id},
        headers=auth_headers,
    )
    assert {o["change_id"] for o in by_change.json()} == {change_id}

    by_category = await client.get(
        "/api/v1/regulatory/obligations/",
        params={"category": "LABELING"},
        headers=auth_headers,
    )
    assert len(by_category.json()) == 1

    none_match = await client.get(
        "/api/v1/regulatory/obligations/",
        params={"category": "CYBERSECURITY"},
        headers=auth_headers,
    )
    assert none_match.json() == []


@pytest.mark.asyncio
async def test_changes_are_filterable_by_document_and_type(
    client, auth_headers, seeded_assessment
):
    one = await client.get(
        f"/api/v1/regulatory/changes/{seeded_assessment['regulatory_change_id']}",
        headers=auth_headers,
    )
    document_id = one.json()["document_id"]

    by_document = await client.get(
        "/api/v1/regulatory/changes/",
        params={"document_id": document_id},
        headers=auth_headers,
    )
    assert {c["document_id"] for c in by_document.json()} == {document_id}

    wrong_type = await client.get(
        "/api/v1/regulatory/changes/",
        params={"change_type": "SAFETY_CHANGE"},
        headers=auth_headers,
    )
    assert wrong_type.json() == []


@pytest.mark.asyncio
async def test_an_unknown_change_or_obligation_is_404(client, auth_headers, demo_org):
    assert (
        await client.get("/api/v1/regulatory/changes/nope", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get("/api/v1/regulatory/obligations/nope", headers=auth_headers)
    ).status_code == 404
    # An unknown change's obligations is a 404, not an empty list: "no obligations"
    # and "no such change" are different answers.
    assert (
        await client.get(
            "/api/v1/regulatory/changes/nope/obligations", headers=auth_headers
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_one_tenant_cannot_read_another_tenants_intelligence(
    client, auth_headers, seeded_assessment
):
    """
    The test that justifies the join. Neither table has an organization_id, so
    without joining the parent document this would return the other tenant's rows.
    """
    from app.tests.test_impact_isolation import _register_org

    ours = seeded_assessment["regulatory_change_id"]
    org_b_id, headers_b = await _register_org(client, "rival-devices-intel")

    # Give the second tenant a change of its own, so an empty result cannot be
    # mistaken for "the endpoint returns nothing to anybody".
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="EMA", jurisdiction="European Union", country="BEL"
        )
        theirs = await create_change(
            session,
            organization_id=org_b_id,
            authority=authority,
            summary="Unrelated European labeling revision.",
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )

    their_view = await client.get(
        "/api/v1/regulatory/changes/", headers=headers_b
    )
    assert their_view.status_code == 200
    ids = {c["id"] for c in their_view.json()}
    assert theirs in ids
    assert ours not in ids

    # And by id, ours reads as missing to them.
    assert (
        await client.get(f"/api/v1/regulatory/changes/{ours}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/regulatory/changes/{ours}/obligations", headers=headers_b
        )
    ).status_code == 404

    their_obligations = await client.get(
        "/api/v1/regulatory/obligations/", headers=headers_b
    )
    assert {o["change_id"] for o in their_obligations.json()} == {theirs}


@pytest.mark.asyncio
async def test_the_pipeline_owns_these_rows_so_they_are_not_writable(
    client, auth_headers, seeded_assessment
):
    """
    Read-only on purpose. These rows are what the document pipeline extracted;
    hand-editing an obligation would destroy the provenance that makes it useful.
    """
    change_id = seeded_assessment["regulatory_change_id"]
    for method, url in (
        ("POST", "/api/v1/regulatory/changes/"),
        ("PATCH", f"/api/v1/regulatory/changes/{change_id}"),
        ("DELETE", f"/api/v1/regulatory/changes/{change_id}"),
        ("POST", "/api/v1/regulatory/obligations/"),
    ):
        res = await client.request(method, url, headers=auth_headers)
        assert res.status_code == 405, f"{method} {url} -> {res.status_code}"


@pytest.mark.asyncio
async def test_intelligence_requires_authentication(client, demo_org):
    assert (await client.get("/api/v1/regulatory/changes/")).status_code == 401
    assert (await client.get("/api/v1/regulatory/obligations/")).status_code == 401
