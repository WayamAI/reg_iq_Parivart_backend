"""
Evidence over HTTP: attach, list, read, download, and the boundaries.

The interesting cases are the boundaries. Evidence can only hang off an action the
tenant owns, the check must happen before any byte is written, the internal storage
key must never reach a client, and a record whose bytes have gone must not be
reported as a record that never existed.
"""

import io

import pytest
from sqlalchemy import func, select

from app.db.database import AsyncSessionLocal
from app.models.governance import Evidence
from app.services.audit_service import EVENT_EVIDENCE_ATTACHED


async def _make_action(client, headers, impact_item_id: str, title="Update labeling") -> str:
    res = await client.post(
        "/api/v1/actions/",
        json={"title": title, "impact_item_id": impact_item_id},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _file(content: bytes = b"signed-off labeling change", name: str = "signoff.txt"):
    return {"file": (name, io.BytesIO(content), "text/plain")}


@pytest.mark.asyncio
async def test_attach_then_read_then_download(client, auth_headers, seeded_assessment):
    action_id = await _make_action(
        client, auth_headers, seeded_assessment["impact_item_id"]
    )

    res = await client.post(
        "/api/v1/evidence/upload",
        files=_file(),
        data={"action_id": action_id, "description": "Signed off by QA."},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["action_id"] == action_id
    assert body["filename"] == "signoff.txt"
    assert body["description"] == "Signed off by QA."
    # sha256 of the uploaded bytes, recorded as the integrity anchor.
    assert len(body["sha256"]) == 64
    # The uploader is the token's user, resolved to a name, not just an id.
    assert body["uploaded_by_email"] == "admin@asterion.com"

    got = await client.get(f"/api/v1/evidence/{body['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]

    dl = await client.get(
        f"/api/v1/evidence/{body['id']}/download", headers=auth_headers
    )
    assert dl.status_code == 200
    assert dl.content == b"signed-off labeling change"
    assert "attachment" in dl.headers["content-disposition"]


@pytest.mark.asyncio
async def test_the_internal_storage_key_never_reaches_a_client(
    client, auth_headers, seeded_assessment
):
    """It is a filesystem path. A client has no use for it and should not see it."""
    action_id = await _make_action(
        client, auth_headers, seeded_assessment["impact_item_id"]
    )
    created = (
        await client.post(
            "/api/v1/evidence/upload",
            files=_file(),
            data={"action_id": action_id},
            headers=auth_headers,
        )
    ).json()

    assert "storage_key" not in created
    listed = (await client.get("/api/v1/evidence/", headers=auth_headers)).json()
    assert all("storage_key" not in row for row in listed)

    # It is stored, though -- the download path needs it.
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(Evidence).where(Evidence.id == created["id"])
            )
        ).scalars().first()
        assert row.storage_key


@pytest.mark.asyncio
async def test_listing_is_a_bare_array_filterable_by_action(
    client, auth_headers, seeded_assessment
):
    item = seeded_assessment["impact_item_id"]
    first = await _make_action(client, auth_headers, item, title="First")
    second = await _make_action(client, auth_headers, item, title="Second")

    for action_id in (first, first, second):
        res = await client.post(
            "/api/v1/evidence/upload",
            files=_file(),
            data={"action_id": action_id},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text

    everything = await client.get("/api/v1/evidence/", headers=auth_headers)
    assert isinstance(everything.json(), list)
    assert len(everything.json()) == 3

    for_first = await client.get(
        "/api/v1/evidence/", params={"action_id": first}, headers=auth_headers
    )
    assert len(for_first.json()) == 2
    assert {row["action_id"] for row in for_first.json()} == {first}


@pytest.mark.asyncio
async def test_the_same_file_can_be_evidence_for_two_actions(
    client, auth_headers, seeded_assessment
):
    """
    Unlike a regulatory document, evidence is not deduplicated by hash: one file can
    legitimately substantiate two actions, and refusing the second would lose the
    fact that it was offered for both.
    """
    item = seeded_assessment["impact_item_id"]
    first = await _make_action(client, auth_headers, item, title="One")
    second = await _make_action(client, auth_headers, item, title="Two")

    hashes = []
    for action_id in (first, second):
        res = await client.post(
            "/api/v1/evidence/upload",
            files=_file(b"identical bytes", "same.txt"),
            data={"action_id": action_id},
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        hashes.append(res.json()["sha256"])

    assert hashes[0] == hashes[1]
    assert len((await client.get("/api/v1/evidence/", headers=auth_headers)).json()) == 2


@pytest.mark.asyncio
async def test_attaching_records_an_audit_event_against_the_action(
    client, auth_headers, seeded_assessment
):
    action_id = await _make_action(
        client, auth_headers, seeded_assessment["impact_item_id"]
    )
    created = (
        await client.post(
            "/api/v1/evidence/upload",
            files=_file(),
            data={"action_id": action_id},
            headers=auth_headers,
        )
    ).json()

    res = await client.get(
        "/api/v1/audit/",
        params={"event_type": EVENT_EVIDENCE_ATTACHED},
        headers=auth_headers,
    )
    assert res.status_code == 200
    events = res.json()
    assert len(events) == 1
    # Recorded against the action, because the trail is read as the history of the work.
    assert events[0]["entity_id"] == action_id
    assert events[0]["payload"]["evidence_id"] == created["id"]
    assert events[0]["payload"]["sha256"] == created["sha256"]


@pytest.mark.asyncio
async def test_an_unknown_action_is_404_and_writes_nothing(
    client, auth_headers, demo_org
):
    before = await _count_evidence()
    res = await client.post(
        "/api/v1/evidence/upload",
        files=_file(),
        data={"action_id": "does-not-exist"},
        headers=auth_headers,
    )
    assert res.status_code == 404
    assert await _count_evidence() == before


@pytest.mark.asyncio
async def test_another_tenants_action_is_not_a_valid_attachment_point(
    client, auth_headers, seeded_assessment
):
    """
    The important one: ownership is checked before the file is stored, so a caller
    aiming at another tenant's action does not even cause a write.
    """
    from app.tests.test_impact_isolation import _register_org

    action_id = await _make_action(
        client, auth_headers, seeded_assessment["impact_item_id"]
    )
    _, headers_b = await _register_org(client, "rival-devices-evidence")

    before = await _count_evidence()
    res = await client.post(
        "/api/v1/evidence/upload",
        files=_file(),
        data={"action_id": action_id},
        headers=headers_b,
    )
    # Missing, not forbidden: the response must not confirm the action exists.
    assert res.status_code == 404
    assert await _count_evidence() == before


@pytest.mark.asyncio
async def test_another_tenant_cannot_read_or_download_our_evidence(
    client, auth_headers, seeded_assessment
):
    from app.tests.test_impact_isolation import _register_org

    action_id = await _make_action(
        client, auth_headers, seeded_assessment["impact_item_id"]
    )
    created = (
        await client.post(
            "/api/v1/evidence/upload",
            files=_file(),
            data={"action_id": action_id},
            headers=auth_headers,
        )
    ).json()

    _, headers_b = await _register_org(client, "rival-devices-evidence-read")

    assert (await client.get("/api/v1/evidence/", headers=headers_b)).json() == []
    assert (
        await client.get(f"/api/v1/evidence/{created['id']}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/evidence/{created['id']}/download", headers=headers_b
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_a_record_whose_file_is_gone_is_410_not_404(
    client, auth_headers, seeded_assessment
):
    """
    Distinguishable on purpose: a 404 would say the evidence was never filed, which
    is a different and more alarming claim than "the bytes are no longer there".
    """
    import os

    from app.services.document_service import storage

    action_id = await _make_action(
        client, auth_headers, seeded_assessment["impact_item_id"]
    )
    created = (
        await client.post(
            "/api/v1/evidence/upload",
            files=_file(),
            data={"action_id": action_id},
            headers=auth_headers,
        )
    ).json()

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(Evidence).where(Evidence.id == created["id"])
            )
        ).scalars().first()
        os.remove(os.path.join(storage.base_path, row.storage_key))

    res = await client.get(
        f"/api/v1/evidence/{created['id']}/download", headers=auth_headers
    )
    assert res.status_code == 410


@pytest.mark.asyncio
async def test_evidence_requires_authentication(client, demo_org):
    assert (await client.get("/api/v1/evidence/")).status_code == 401
    assert (
        await client.post(
            "/api/v1/evidence/upload", files=_file(), data={"action_id": "x"}
        )
    ).status_code == 401


async def _count_evidence() -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(Evidence))
