"""
POST /regulatory/sources/{id}/run for an API/WEB_SERVICE source, end to end over
HTTP: the fetch is monkeypatched (no network), everything else -- auth, role
gating, tenant attribution, persistence, run counters -- is the real path.
"""

import json
import uuid

import pytest

from app.ingestion import api_adapter
from app.ingestion.rss_fetcher import FeedFetchError
from app.storage.base import LocalStorage

PAYLOAD = json.dumps({"title": "HTTP Test API Notice", "body": "Fetched over the real run_source endpoint."}).encode()


@pytest.fixture(autouse=True)
def _use_tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(api_adapter, "storage", LocalStorage(base_path=str(tmp_path)))


async def _async_return(value):
    return value


async def _source(client, auth_headers, source_type: str) -> dict:
    authority = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": f"API HTTP Test Authority {source_type}",
            "short_name": f"AHTA-{uuid.uuid4().hex[:6]}",
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
            "name": f"API HTTP Test Source {source_type}",
            "source_type": source_type,
            "connector_type": source_type,
            "url": "https://authority.example/api/notices",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert source.status_code == 201, source.text
    return source.json()


async def test_running_an_api_source_creates_a_document(client, auth_headers, monkeypatch):
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(PAYLOAD))
    source = await _source(client, auth_headers, "API")

    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["documents_discovered"] == 1
    assert run["documents_processed"] == 1
    assert run["documents_failed"] == 0

    documents = await client.get("/api/v1/regulatory/documents/", headers=auth_headers)
    titles = {d["title"] for d in documents.json()}
    assert source["name"] in titles


async def test_running_a_web_service_source_dispatches_to_the_same_adapter(client, auth_headers, monkeypatch):
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(PAYLOAD))
    source = await _source(client, auth_headers, "WEB_SERVICE")

    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["documents_processed"] == 1


async def test_fetch_failure_reports_failed_not_an_eternal_queued(client, auth_headers, monkeypatch):
    def _raise(url, **kwargs):
        raise FeedFetchError("simulated upstream outage")

    monkeypatch.setattr(api_adapter, "fetch_feed", _raise)
    source = await _source(client, auth_headers, "API")

    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "FAILED"
    assert "simulated upstream outage" in run["error"]
    assert run["documents_processed"] == 0
    assert run["completed_at"] is not None


async def test_repeated_run_does_not_duplicate_documents(client, auth_headers, monkeypatch):
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(PAYLOAD))
    source = await _source(client, auth_headers, "API")

    first = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    second = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["status"] == "COMPLETED"

    documents = await client.get("/api/v1/regulatory/documents/", headers=auth_headers)
    matching = [d for d in documents.json() if d["title"] == source["name"]]
    assert len(matching) == 1


async def test_run_source_still_requires_configure_role_for_api(client, auth_headers, monkeypatch):
    from app.tests.conftest import role_headers

    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(PAYLOAD))
    source = await _source(client, auth_headers, "API")

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=viewer
    )
    assert response.status_code == 403
