"""
Regulatory sources API: two independent regression fixes found by direct inspection
while documenting ingestion-run status (docs/ingestion/INGESTION_RUN_STATUS.md).

1. create_source referenced RegulatoryAuthority without importing it anywhere in the
   module -- a NameError on every single call, never covered by an existing test.

2. run_source always created a QUEUED IngestionRun with no code path that ever
   transitions it. The frontend's own TERMINAL_INGESTION_STATES (src/services/api/
   types.ts in the sibling frontend repo) treats QUEUED as non-terminal and polls
   waiting for it to settle -- a run that can never leave QUEUED silently looks
   identical to one still legitimately in progress. For a source_type with no adapter,
   the run is now marked FAILED immediately with an explicit reason -- an existing
   terminal state on both sides, no API contract or response-shape change. These tests
   use source_type=API specifically to exercise that still-unimplemented path; RSS and
   HTML now have real adapters (app/ingestion/rss_ingestion.py,
   app/ingestion/html_adapter.py) and are covered separately in
   test_rss_source_run_api.py / test_html_adapter.py.
"""

import uuid

import pytest

from app.models.regulatory import IngestionStatus


async def _authority_payload(client, auth_headers) -> str:
    response = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": "Sources Test Authority",
            "short_name": f"STA-{uuid.uuid4().hex[:6]}",
            "jurisdiction": "Testland",
            "country": "Testland",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_create_source_does_not_raise_nameerror(client, auth_headers):
    """Regression test: this endpoint previously raised NameError on every call
    because RegulatoryAuthority was used but never imported."""
    authority_id = await _authority_payload(client, auth_headers)

    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Test RSS Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["authority_id"] == authority_id
    assert body["name"] == "Test RSS Source"


async def test_create_source_with_a_url_does_not_raise_a_binding_error(client, auth_headers):
    """Regression test: source_in.url is a pydantic HttpUrl, not a str, and passing it
    straight through to the ORM failed at the driver level ("type 'HttpUrl' is not
    supported")."""
    authority_id = await _authority_payload(client, auth_headers)

    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source With URL",
            "source_type": "RSS",
            "connector_type": "RSS",
            "url": "https://example.com/feed.xml",
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["url"] == "https://example.com/feed.xml"


async def test_update_source_with_a_url_does_not_raise_a_binding_error(client, auth_headers):
    authority_id = await _authority_payload(client, auth_headers)
    created = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source To Update",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    response = await client.patch(
        f"/api/v1/regulatory/sources/{created.json()['id']}",
        json={"url": "https://example.com/updated-feed.xml"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["url"] == "https://example.com/updated-feed.xml"


async def test_create_source_without_a_url_succeeds_with_url_null(client, auth_headers):
    """url is Optional[HttpUrl] -- a DOCUMENT/manual source legitimately has none."""
    authority_id = await _authority_payload(client, auth_headers)

    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source Without URL",
            "source_type": "DOCUMENT",
            "connector_type": "DOCUMENT",
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["url"] is None


async def test_create_source_rejects_an_invalid_url(client, auth_headers):
    """Validation must still reject a malformed URL -- the fix stringifies an already-
    validated HttpUrl for the ORM, it does not relax validation to accept anything."""
    authority_id = await _authority_payload(client, auth_headers)

    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source With Bad URL",
            "source_type": "RSS",
            "connector_type": "RSS",
            "url": "not a valid url",
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_update_source_rejects_an_invalid_url(client, auth_headers):
    authority_id = await _authority_payload(client, auth_headers)
    created = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source To Bad-Update",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    response = await client.patch(
        f"/api/v1/regulatory/sources/{created.json()['id']}",
        json={"url": "ht!tp://not-a-url"},
        headers=auth_headers,
    )

    assert response.status_code == 422


async def test_update_source_can_clear_a_url_back_to_null(client, auth_headers):
    authority_id = await _authority_payload(client, auth_headers)
    created = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source To Clear",
            "source_type": "RSS",
            "connector_type": "RSS",
            "url": "https://example.com/feed.xml",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    response = await client.patch(
        f"/api/v1/regulatory/sources/{created.json()['id']}",
        json={"url": ""},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["url"] is None


async def test_persisted_url_round_trips_correctly_on_a_fresh_get(client, auth_headers):
    """Not just the create/update response -- a separate GET (a genuinely fresh read
    from the database, not an in-memory ORM object) must also serialize the stored
    url as a plain string, confirming it was actually persisted as one."""
    authority_id = await _authority_payload(client, auth_headers)
    created = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Source To Reread",
            "source_type": "RSS",
            "connector_type": "RSS",
            "url": "https://example.com/reread-feed.xml",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    fetched = await client.get(
        f"/api/v1/regulatory/sources/{created.json()['id']}", headers=auth_headers
    )

    assert fetched.status_code == 200
    assert fetched.json()["url"] == "https://example.com/reread-feed.xml"


async def test_create_source_404s_for_an_unknown_authority(client, auth_headers):
    """The RegulatoryAuthority lookup this endpoint performs must still correctly
    reject an unknown authority_id now that the import is fixed."""
    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": "does-not-exist",
            "name": "Test Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "not found" in response.text.lower()


async def _created_source(client, auth_headers, source_type="API", connector_type="API") -> dict:
    authority_id = await _authority_payload(client, auth_headers)
    response = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": f"Test Source {uuid.uuid4().hex[:6]}",
            "source_type": source_type,
            "connector_type": connector_type,
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_run_source_reports_failed_not_an_eternal_queued(client, auth_headers):
    # DOCUMENT is manual-upload-only and deliberately has no run adapter (RSS, HTML,
    # API and WEB_SERVICE all do) -- this is what exercises the "no adapter
    # implemented" path below.
    source = await _created_source(client, auth_headers, source_type="DOCUMENT", connector_type="DOCUMENT")

    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == IngestionStatus.FAILED.value
    assert run["error"]
    assert "DOCUMENT" in run["error"]
    assert run["completed_at"] is not None


async def test_run_source_still_404s_for_an_unknown_source(client, auth_headers):
    response = await client.post(
        "/api/v1/regulatory/sources/does-not-exist/run", headers=auth_headers
    )
    assert response.status_code == 404


async def test_run_source_still_rejects_a_disabled_source(client, auth_headers):
    authority_id = await _authority_payload(client, auth_headers)
    created = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority_id,
            "name": "Disabled Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "enabled": False,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    response = await client.post(
        f"/api/v1/regulatory/sources/{created.json()['id']}/run", headers=auth_headers
    )
    assert response.status_code == 400


async def test_run_source_result_is_visible_via_get_run(client, auth_headers):
    """The frontend polls GET /sources/runs/{run_id}; it must see the same settled
    FAILED status, not a stale QUEUED row."""
    source = await _created_source(client, auth_headers)
    run = (
        await client.post(
            f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
        )
    ).json()

    fetched = await client.get(
        f"/api/v1/regulatory/sources/runs/{run['id']}", headers=auth_headers
    )

    assert fetched.status_code == 200
    assert fetched.json()["status"] == IngestionStatus.FAILED.value
