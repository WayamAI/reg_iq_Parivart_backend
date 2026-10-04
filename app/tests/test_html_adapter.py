"""
app/ingestion/html_adapter.run_html_ingestion: fetch (monkeypatched, no network) ->
extract -> persist -> run summary, against the real database and storage.
"""

import uuid

import pytest

from app.ingestion import html_adapter
from app.ingestion.rss_fetcher import FeedFetchError
from app.models.document import RegulatoryDocument
from app.models.regulatory import ConnectorType, RegulatoryAuthority, RegulatorySource, SourceType
from app.storage.base import LocalStorage

VALID_PAGE = b"""
<html>
  <head><title>Important Regulatory Notice</title></head>
  <body>
    <nav>Home | About | Contact</nav>
    <script>trackPageView();</script>
    <style>.notice { color: red; }</style>
    <main>
      <h1>Important Regulatory Notice</h1>
      <p>All manufacturers must comply with the new labelling requirement by Q1 2027.</p>
    </main>
  </body>
</html>
"""

NO_TITLE_PAGE = b"<html><body><p>Content with no title tag at all.</p></body></html>"

EMPTY_PAGE = b"<html><head></head><body>   \n   </body></html>"


async def _source(session) -> RegulatorySource:
    authority = RegulatoryAuthority(
        id=str(uuid.uuid4()),
        name="HTML Test Authority",
        short_name=f"HTA-{uuid.uuid4().hex[:6]}",
        jurisdiction="Testland",
        country="Testland",
        is_active=True,
    )
    session.add(authority)
    await session.flush()

    source = RegulatorySource(
        id=str(uuid.uuid4()),
        authority_id=authority.id,
        name=f"HTML Test Source {uuid.uuid4().hex[:6]}",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        source_type=SourceType.HTML,
        connector_type=ConnectorType.HTML,
        url="https://authority.example/notice.html",
        enabled=True,
    )
    session.add(source)
    await session.flush()
    return source


def _patch_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(html_adapter, "storage", LocalStorage(base_path=str(tmp_path)))


async def _async_return(value):
    return value


async def test_successful_page_creates_one_document(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(VALID_PAGE))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await html_adapter.run_html_ingestion(
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
        assert docs[0].title == "Important Regulatory Notice"
        # script/style/nav content stripped; substantive paragraph text present.
        assert "trackPageView" not in docs[0].extracted_text
        assert "color: red" not in docs[0].extracted_text
        assert "new labelling requirement" in docs[0].extracted_text


async def test_repeated_run_is_idempotent(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(VALID_PAGE))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        source_id = source.id
        await html_adapter.run_html_ingestion(session, source=source, organization_id=demo_org.id)

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        source = (
            await session.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
        ).scalars().first()
        status, _, counters = await html_adapter.run_html_ingestion(
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


async def test_missing_title_falls_back_to_source_name(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(NO_TITLE_PAGE))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await html_adapter.run_html_ingestion(
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
        assert doc.title == source.name


async def test_empty_page_reports_failed_not_completed(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(EMPTY_PAGE))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await html_adapter.run_html_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "no extractable text" in error
    assert counters["documents_processed"] == 0


async def test_fetch_failure_reports_failed_without_crashing(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    def _raise(url, **kwargs):
        raise FeedFetchError("simulated html fetch failure")

    monkeypatch.setattr(html_adapter, "fetch_feed", _raise)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await html_adapter.run_html_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "simulated html fetch failure" in error
    assert counters["documents_discovered"] == 1
    assert counters["documents_downloaded"] == 0


async def test_malformed_html_does_not_crash(demo_org, tmp_path, monkeypatch):
    """BeautifulSoup's html.parser is itself lenient with malformed markup; this
    confirms the adapter doesn't additionally assume well-formed input anywhere."""
    from app.db.database import AsyncSessionLocal

    malformed = b"<html><head><title>Broken<body><p>Unclosed tags everywhere<div>"
    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(malformed))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await html_adapter.run_html_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "COMPLETED"
    assert counters["documents_processed"] == 1


async def test_missing_url_fails_without_attempting_a_fetch(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    called = {"count": 0}

    def _should_not_be_called(url, **kwargs):
        called["count"] += 1
        return _async_return(VALID_PAGE)

    monkeypatch.setattr(html_adapter, "fetch_feed", _should_not_be_called)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        source.url = None
        await session.flush()

        status, error, counters = await html_adapter.run_html_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "no url" in error
    assert called["count"] == 0
