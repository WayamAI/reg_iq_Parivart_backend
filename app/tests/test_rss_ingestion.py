"""
app/ingestion/rss_ingestion.run_rss_ingestion: fetch (monkeypatched, no network) ->
parse -> persist -> run summary, against the real database and storage.
"""

import uuid

import pytest

from app.ingestion import rss_ingestion
from app.ingestion.rss_fetcher import FeedFetchError
from app.models.document import RegulatoryDocument
from app.models.regulatory import ConnectorType, RegulatoryAuthority, RegulatorySource, SourceType
from app.storage.base import LocalStorage

TWO_ENTRY_FEED = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Notice A</title>
      <link>https://authority.example/a</link>
      <guid>urn:a</guid>
      <description>Content of notice A.</description>
      <pubDate>Mon, 01 Sep 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Notice B</title>
      <link>https://authority.example/b</link>
      <guid>urn:b</guid>
      <description>Content of notice B.</description>
      <pubDate>Tue, 02 Sep 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ONE_ENTRY_FEED = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Notice A</title>
      <link>https://authority.example/a</link>
      <guid>urn:a</guid>
      <description>Content of notice A.</description>
    </item>
  </channel>
</rss>
"""

EMPTY_FEED = b"<rss version=\"2.0\"><channel></channel></rss>"


async def _source(session) -> RegulatorySource:
    authority = RegulatoryAuthority(
        id=str(uuid.uuid4()),
        name="RSS Test Authority",
        short_name=f"RTA-{uuid.uuid4().hex[:6]}",
        jurisdiction="Testland",
        country="Testland",
        is_active=True,
    )
    session.add(authority)
    await session.flush()

    source = RegulatorySource(
        id=str(uuid.uuid4()),
        authority_id=authority.id,
        name=f"RSS Test Source {uuid.uuid4().hex[:6]}",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        source_type=SourceType.RSS,
        connector_type=ConnectorType.RSS,
        url="https://authority.example/feed.xml",
        enabled=True,
    )
    session.add(source)
    await session.flush()
    return source


def _patch_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(rss_ingestion, "storage", LocalStorage(base_path=str(tmp_path)))


async def test_successful_run_creates_documents(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(TWO_ENTRY_FEED))

    async with AsyncSessionLocal() as session:
        source = await _source(session)

        status, error, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "COMPLETED"
    assert error is None
    assert counters["documents_discovered"] == 2
    assert counters["documents_processed"] == 2
    assert counters["documents_failed"] == 0

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        docs = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().all()
        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert titles == {"Notice A", "Notice B"}
        assert all(d.extracted_text for d in docs)


async def test_repeated_run_is_idempotent(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(ONE_ENTRY_FEED))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        first_status, _, first_counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        source_again = (
            await session.execute(select(RegulatorySource).where(RegulatorySource.id == source.id))
        ).scalars().first()
        second_status, _, second_counters = await rss_ingestion.run_rss_ingestion(
            session, source=source_again, organization_id=demo_org.id
        )

    assert first_counters["documents_processed"] == 1
    assert second_counters["documents_processed"] == 1  # the duplicate, not a new doc
    assert second_status == "COMPLETED"

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        docs = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().all()
        assert len(docs) == 1  # not 2 -- the second run created no new row


async def test_two_organizations_ingesting_the_same_feed_each_get_their_own_documents(
    demo_org, tmp_path, monkeypatch
):
    from app.db.database import AsyncSessionLocal
    from app.models.organization import Organization

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(ONE_ENTRY_FEED))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        other_org = Organization(
            id=str(uuid.uuid4()), name="Other Org", slug=f"other-org-{uuid.uuid4().hex[:8]}"
        )
        session.add(other_org)
        await session.commit()
        other_org_id = other_org.id
        source_id = source.id

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        source = (
            await session.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
        ).scalars().first()
        await rss_ingestion.run_rss_ingestion(session, source=source, organization_id=demo_org.id)

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        source = (
            await session.execute(select(RegulatorySource).where(RegulatorySource.id == source_id))
        ).scalars().first()
        status, _, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=other_org_id
        )

    assert status == "COMPLETED"
    assert counters["documents_processed"] == 1  # a NEW document for this org, not a duplicate

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        all_docs = (await session.execute(select(RegulatoryDocument))).scalars().all()
        assert len(all_docs) == 2
        assert {d.organization_id for d in all_docs} == {demo_org.id, other_org_id}


async def test_fetch_failure_reports_failed_without_crashing(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    def _raise(url, **kwargs):
        raise FeedFetchError("simulated fetch failure")

    monkeypatch.setattr(rss_ingestion, "fetch_feed", _raise)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "simulated fetch failure" in error
    assert counters["documents_discovered"] == 0


async def test_empty_feed_is_a_completed_run_with_zero_items(demo_org, tmp_path, monkeypatch):
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(EMPTY_FEED))

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "COMPLETED"
    assert error is None
    assert counters["documents_discovered"] == 0


async def test_missing_url_fails_without_attempting_a_fetch(demo_org, monkeypatch):
    from app.db.database import AsyncSessionLocal

    called = {"count": 0}

    def _should_not_be_called(url, **kwargs):
        called["count"] += 1
        return _async_return(ONE_ENTRY_FEED)

    monkeypatch.setattr(rss_ingestion, "fetch_feed", _should_not_be_called)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        source.url = None
        await session.flush()

        status, error, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert "no url" in error
    assert called["count"] == 0


async def test_one_bad_entry_among_good_ones_reports_partial(demo_org, tmp_path, monkeypatch):
    """A persistence failure on one entry must not sink entries that already
    succeeded, and must be reported as PARTIAL, not COMPLETED or FAILED."""
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(TWO_ENTRY_FEED))

    real_upload = rss_ingestion.storage.upload_file

    async def _fail_for_notice_b(file_data, file_name, content_type):
        if "urn:b" in file_name:
            raise OSError("simulated storage failure for this entry")
        return await real_upload(file_data, file_name, content_type)

    monkeypatch.setattr(rss_ingestion.storage, "upload_file", _fail_for_notice_b)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "PARTIAL"
    assert error  # a summary of what failed, not None
    assert counters["documents_discovered"] == 2
    assert counters["documents_processed"] == 1  # Notice A only
    assert counters["documents_failed"] == 1  # Notice B

    async with AsyncSessionLocal() as session:
        from sqlalchemy.future import select

        docs = (
            await session.execute(
                select(RegulatoryDocument).where(RegulatoryDocument.organization_id == demo_org.id)
            )
        ).scalars().all()
        assert len(docs) == 1
        assert docs[0].title == "Notice A"


async def test_every_entry_failing_reports_failed_not_partial(demo_org, tmp_path, monkeypatch):
    """When nothing succeeds, the result is FAILED, not PARTIAL -- PARTIAL implies
    at least one entry actually made it through."""
    from app.db.database import AsyncSessionLocal

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(TWO_ENTRY_FEED))

    async def _always_fail(file_data, file_name, content_type):
        raise OSError("simulated total storage failure")

    monkeypatch.setattr(rss_ingestion.storage, "upload_file", _always_fail)

    async with AsyncSessionLocal() as session:
        source = await _source(session)
        status, error, counters = await rss_ingestion.run_rss_ingestion(
            session, source=source, organization_id=demo_org.id
        )

    assert status == "FAILED"
    assert counters["documents_processed"] == 0
    assert counters["documents_failed"] == 2


async def _async_return(value):
    return value
