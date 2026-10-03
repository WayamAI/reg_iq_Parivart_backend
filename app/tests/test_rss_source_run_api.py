"""
POST /regulatory/sources/{id}/run for an RSS source, end to end over HTTP: the
fetch is monkeypatched (no network), everything else -- auth, role gating, tenant
attribution, persistence, run counters -- is the real path.
"""

import uuid

import pytest

from app.ingestion import rss_ingestion
from app.storage.base import LocalStorage


@pytest.fixture(autouse=True)
def _use_tmp_storage(tmp_path, monkeypatch):
    """Every test in this file triggers a real ingestion run, which writes entry
    content to storage -- redirect it to a throwaway directory instead of the real
    ./storage used outside tests."""
    monkeypatch.setattr(rss_ingestion, "storage", LocalStorage(base_path=str(tmp_path)))

FEED = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>HTTP Test Notice</title>
      <link>https://authority.example/notice</link>
      <guid>urn:http-test</guid>
      <description>Fetched over the real run_source endpoint.</description>
    </item>
  </channel>
</rss>
"""


async def _async_return(value):
    return value


async def _rss_source(client, auth_headers) -> dict:
    authority = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": "RSS HTTP Test Authority",
            "short_name": f"RHTA-{uuid.uuid4().hex[:6]}",
            "jurisdiction": "Testland",
            "country": "Testland",
        },
        headers=auth_headers,
    )
    assert authority.status_code == 201, authority.text

    source = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority.json()["id"],
            "name": "RSS HTTP Test Source",
            "source_type": "RSS",
            "connector_type": "RSS",
            "url": "https://authority.example/feed.xml",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert source.status_code == 201, source.text
    return source.json()


async def test_running_an_rss_source_creates_a_document(client, auth_headers, monkeypatch):
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(FEED))

    source = await _rss_source(client, auth_headers)

    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["documents_discovered"] == 1
    assert run["documents_processed"] == 1
    assert run["documents_failed"] == 0
    assert run["completed_at"] is not None

    documents = await client.get("/api/v1/regulatory/documents/", headers=auth_headers)
    assert documents.status_code == 200
    titles = {d["title"] for d in documents.json()}
    assert "HTTP Test Notice" in titles


async def test_running_the_same_rss_source_twice_does_not_duplicate(client, auth_headers, monkeypatch):
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(FEED))
    source = await _rss_source(client, auth_headers)

    first = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )
    second = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert first.json()["documents_processed"] == 1
    assert second.json()["documents_processed"] == 1  # the duplicate, not a new one
    assert second.json()["status"] == "COMPLETED"

    documents = await client.get("/api/v1/regulatory/documents/", headers=auth_headers)
    matching = [d for d in documents.json() if d["title"] == "HTTP Test Notice"]
    assert len(matching) == 1


async def test_rss_fetch_failure_reports_failed_over_http(client, auth_headers, monkeypatch):
    from app.ingestion.rss_fetcher import FeedFetchError

    def _raise(url, **kwargs):
        raise FeedFetchError("simulated over HTTP")

    monkeypatch.setattr(rss_ingestion, "fetch_feed", _raise)
    source = await _rss_source(client, auth_headers)

    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "FAILED"
    assert "simulated over HTTP" in run["error"]


async def test_run_source_still_requires_configure_role_for_rss(client, auth_headers, monkeypatch):
    from app.tests.conftest import role_headers

    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(FEED))
    source = await _rss_source(client, auth_headers)

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=viewer
    )
    assert response.status_code == 403
