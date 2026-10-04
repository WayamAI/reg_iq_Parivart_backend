"""
POST /regulatory/sources/{id}/run for an HTML source, end to end over HTTP: the
fetch is monkeypatched (no network), everything else -- auth, role gating, tenant
attribution, persistence, run counters -- is the real path.
"""

import uuid

import pytest

from app.ingestion import html_adapter
from app.storage.base import LocalStorage

PAGE = b"""
<html><head><title>HTTP Test HTML Notice</title></head>
<body><p>Fetched over the real run_source endpoint for an HTML source.</p></body></html>
"""


@pytest.fixture(autouse=True)
def _use_tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(html_adapter, "storage", LocalStorage(base_path=str(tmp_path)))


async def _async_return(value):
    return value


async def _html_source(client, auth_headers) -> dict:
    authority = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": "HTML HTTP Test Authority",
            "short_name": f"HHTA-{uuid.uuid4().hex[:6]}",
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
            "name": "HTML HTTP Test Source",
            "source_type": "HTML",
            "connector_type": "HTML",
            "url": "https://authority.example/notice.html",
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert source.status_code == 201, source.text
    return source.json()


async def test_running_an_html_source_creates_a_document(client, auth_headers, monkeypatch):
    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(PAGE))
    source = await _html_source(client, auth_headers)

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
    assert "HTTP Test HTML Notice" in titles


async def test_run_source_still_requires_configure_role_for_html(client, auth_headers, monkeypatch):
    from app.tests.conftest import role_headers

    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(PAGE))
    source = await _html_source(client, auth_headers)

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(
        f"/api/v1/regulatory/sources/{source['id']}/run", headers=viewer
    )
    assert response.status_code == 403
