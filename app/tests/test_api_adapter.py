"""
app/ingestion/api_adapter.run_api_ingestion: fetch (monkeypatched, no network) ->
parse JSON -> persist -> run summary, against the real database and storage.
"""

import json
import uuid

import pytest

from app.ingestion import api_adapter
from app.ingestion.rss_fetcher import FeedFetchError
from app.models.document import RegulatoryDocument
from app.models.regulatory import ConnectorType, RegulatoryAuthority, RegulatorySource, SourceType
from app.storage.base import LocalStorage

VALID_PAYLOAD = json.dumps({"title": "Weekly Regulatory Bulletin", "body": "New filing deadline is Q1 2027."}).encode()

NO_TEXT_KEY_PAYLOAD = json.dumps({"id": 42, "items": [1, 2, 3]}).encode()

INVALID_JSON = b"{not valid json"


async def _source(session) -> RegulatorySource:
    authority = RegulatoryAuthority(
        id=str(uuid.uuid4()),
        name="API Test Authority",
        short_name=f"ATA-{uuid.uuid4().hex[:6]}",
        jurisdiction="Testland",
        country="Testland",
        is_active=True,
    )
    session.add(authority)
    await session.flush()

    source = RegulatorySource(
        id=str(uuid.uuid4()),
        authority_id=authority.id,
        name=f"API Test Source {uuid.uuid4().hex[:6]}",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        source_type=SourceType.API,
        connector_type=ConnectorType.API,
        url="https://authority.example/api/notices",
        enabled=True,
    )
    session.add(source)
    await session.flush()
    return source


def _patch_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(api_adapter, "storage", LocalStorage(base_path=str(tmp_path)))


async def _async_return(value):
    return value


async def test_successful_response_creates_one_document(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(VALID_PAYLOAD))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "COMPLETED"
    assert error is None
    assert counters == {
        "documents_discovered": 1,
        "documents_downloaded": 1,
        "documents_processed": 1,
        "documents_failed": 0,
    }

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        docs = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().all()
        assert len(docs) == 1
        assert docs[0].title == source.name
        assert docs[0].extracted_text == "Weekly Regulatory Bulletin"


async def test_no_text_key_falls_back_to_json_dump(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(NO_TEXT_KEY_PAYLOAD))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "COMPLETED"
    assert counters["documents_processed"] == 1

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        doc = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().first()
        assert '"id": 42' in doc.extracted_text


async def test_invalid_json_reports_failed_not_completed(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(INVALID_JSON))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "invalid JSON" in error
    assert counters["documents_processed"] == 0


async def test_fetch_failure_reports_failed_without_crashing(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    def _raise(url, **kwargs):
        raise FeedFetchError("simulated api fetch failure")

    monkeypatch.setattr(api_adapter, "fetch_feed", _raise)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "simulated api fetch failure" in error
    assert counters["documents_discovered"] == 1
    assert counters["documents_downloaded"] == 0


async def test_non_success_http_response_reports_failed(demo_org, monkeypatch):
    """fetch_feed itself raises FeedFetchError for non-2xx responses; the adapter
    must surface that as FAILED rather than letting it escape."""
    from app.db.database import AsyncSessionLocal

    def _raise(url, **kwargs):
        raise FeedFetchError("unexpected status code 503")

    monkeypatch.setattr(api_adapter, "fetch_feed", _raise)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "503" in error


async def test_oversized_response_reports_failed_not_completed(demo_org, monkeypatch):
    """fetch_feed enforces its own size cap and raises FeedFetchError; the adapter
    must not crash or treat that as success."""
    from app.db.database import AsyncSessionLocal

    def _raise(url, **kwargs):
        raise FeedFetchError("response exceeded max_response_bytes")

    monkeypatch.setattr(api_adapter, "fetch_feed", _raise)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "exceeded" in error


async def test_unsafe_url_redirect_rejection_reports_failed(demo_org, monkeypatch):
    """fetch_feed re-validates every redirect hop via validate_outbound_url and
    raises FeedFetchError if a hop resolves somewhere unsafe; confirm the adapter
    does not bypass or swallow that into a false success."""
    from app.db.database import AsyncSessionLocal
    from app.ingestion.url_safety import UnsafeUrlError

    def _raise(url, **kwargs):
        raise FeedFetchError(f"redirect blocked: {UnsafeUrlError('blocked unsafe destination')}")

    monkeypatch.setattr(api_adapter, "fetch_feed", _raise)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "blocked" in error


async def test_repeated_run_is_idempotent(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(VALID_PAYLOAD))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        source_id = source.id
        await api_adapter.run_api_ingestion(session, source=source, organization_id=demo_org.id)

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        source = (
            await session.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
        ).scalars().first()
        status, _, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "COMPLETED"
    assert counters["documents_processed"] == 1  # the duplicate, not a new document

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        docs = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().all()
        assert len(docs) == 1


async def test_tenant_isolation_creates_separate_documents(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal
    from app.models.organization import Organization

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(VALID_PAYLOAD))

    async with AsyncSessionLocal() as session:
        other_org_slug = f"other-org-{uuid.uuid4().hex[:6]}"
        other_org = Organization(id=str(uuid.uuid4()), name=f"Other Org {other_org_slug}", slug=other_org_slug)
        session.add(other_org)
        await session.flush()
        other_org_id = other_org.id

        source = await _source(session)
        await api_adapter.run_api_ingestion(session, source=source, organization_id=demo_org.id)
        await api_adapter.run_api_ingestion(session, source=source, organization_id=other_org_id)

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        docs_a = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().all()
        docs_b = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == other_org_id)
            )
        ).scalars().all()
        assert len(docs_a) == 1
        assert len(docs_b) == 1
        assert docs_a[0].id != docs_b[0].id


async def test_missing_url_fails_without_attempting_a_fetch(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    called = {"count": 0}

    def _should_not_be_called(url, **kwargs):
        called["count"] += 1
        return _async_return(VALID_PAYLOAD)

    monkeypatch.setattr(api_adapter, "fetch_feed", _should_not_be_called)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        source.url = None
        await session.flush()

        status, error, counters = await api_adapter.run_api_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "no url" in error
    assert called["count"] == 0
