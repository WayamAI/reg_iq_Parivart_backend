"""
Orchestrates one RSS ingestion run: fetch -> parse -> normalize -> persist ->
run summary.

Deliberately narrow in scope, per the follow-up plan in
docs/ingestion/INGESTION_RUN_STATUS.md: only RSS, only feed-provided metadata (no
fetching enclosure attachments or linked article pages), bounded to MAX_ENTRIES
per run, and tenant-scoped the same way a manual upload is -- the organization
triggering the run owns the documents it creates.

Design decision worth stating explicitly: RegulatorySource/RegulatoryAuthority are
global (not tenant-scoped) in this codebase, but RegulatoryDocument is tenant-scoped.
There is no "subscription" model deciding which organizations should receive a given
source's content, so this adapter attributes every document it creates to the
organization of the user who triggered the run -- exactly like a manual upload. Two
organizations independently triggering the same source each get their own document
rows (enabled by the per-organization sha256 dedup already in place), rather than the
first organization "claiming" the content.
"""

import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.rss_fetcher import FeedFetchError, fetch_feed
from app.ingestion.rss_parser import FeedEntry, FeedParseError, parse_feed
from app.models.document import DocumentProcessingStatus, DocumentType, RegulatoryDocument
from app.models.regulatory import RegulatorySource
from app.services.audit_service import ENTITY_REGULATORY_DOCUMENT, EVENT_DOCUMENT_UPLOADED, AuditService
from app.services.document_service import check_duplicate_sha256, storage

logger = structlog.get_logger()

MAX_ENTRIES_PER_RUN = 50


class RssIngestionResult:
    def __init__(self):
        self.discovered = 0
        self.created = 0
        self.duplicates = 0
        self.failed = 0
        self.errors: list[str] = []

    def as_counters(self) -> dict:
        return {
            "documents_discovered": self.discovered,
            # No separate download step for RSS: an entry's content IS its feed
            # payload, already in hand once the feed itself was fetched. Downloaded
            # tracks the same count as discovered for this adapter.
            "documents_downloaded": self.discovered,
            "documents_processed": self.created + self.duplicates,
            "documents_failed": self.failed,
        }


def _entry_content(entry: FeedEntry) -> str:
    """What becomes the document's extracted_text. Feed-provided data only -- never
    fetches the entry's own link to pull a fuller article body."""
    return f"{entry.title}\n\n{entry.description}".strip()


async def _persist_entry(
    db: AsyncSession,
    *,
    entry: FeedEntry,
    source: RegulatorySource,
    organization_id: str,
    actor_id: Optional[str],
) -> str:
    """Returns 'created' or 'duplicate'. Raises on a genuine persistence failure."""
    content = _entry_content(entry)
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

    existing = await check_duplicate_sha256(sha256, db, organization_id)
    if existing is not None:
        return "duplicate"

    storage_key = await storage.upload_file(
        io.BytesIO(content.encode("utf-8")),
        file_name=f"{entry.guid or uuid.uuid4().hex}.txt",
        content_type="text/plain",
    )

    document = RegulatoryDocument(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        authority_id=source.authority_id,
        source_id=source.id,
        title=entry.title,
        document_type=DocumentType.NOTICE,
        jurisdiction=source.jurisdiction,
        country=source.country,
        source_url=entry.link,
        storage_key=storage_key,
        mime_type="text/plain",
        file_size=len(content.encode("utf-8")),
        sha256=sha256,
        publication_date=entry.published_at,
        # The feed already gave us the full content: there is nothing further to
        # extract. PARSED (not ANALYZED) is accurate -- analysis is a separate,
        # optional AI step this adapter does not perform or claim to have performed.
        processing_status=DocumentProcessingStatus.PARSED,
        extracted_text=content,
        parsed_at=datetime.now(timezone.utc),
    )
    db.add(document)
    AuditService.record(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        event_type=EVENT_DOCUMENT_UPLOADED,
        entity_type=ENTITY_REGULATORY_DOCUMENT,
        entity_id=document.id,
        payload={
            "title": entry.title,
            "document_type": DocumentType.NOTICE.value,
            "sha256": sha256,
            "authority_id": source.authority_id,
            "source_id": source.id,
            "file_size": document.file_size,
            "ingested_via": "rss",
        },
    )
    await db.flush()
    return "created"


async def run_rss_ingestion(
    db: AsyncSession,
    *,
    source: RegulatorySource,
    organization_id: str,
    actor_id: Optional[str] = None,
) -> tuple[str, Optional[str], dict]:
    """
    Run one RSS ingestion pass for `source`, attributing new documents to
    `organization_id`.

    Returns (status, error, counters) where status is one of "COMPLETED", "PARTIAL",
    or "FAILED" (IngestionStatus values the caller writes onto the IngestionRun), error
    is a short human-readable summary (None on full success), and counters matches
    IngestionRun's own fields. Never raises -- a fetch or parse failure is reported as
    a FAILED result, not an exception, because the caller (the HTTP endpoint) has
    already committed to responding with a run record regardless of outcome.
    """
    if not source.url:
        return "FAILED", "source has no url configured", RssIngestionResult().as_counters()

    try:
        raw = await fetch_feed(source.url)
    except FeedFetchError as exc:
        logger.warning("rss_fetch_failed", source_id=source.id, error=str(exc))
        return "FAILED", f"fetch failed: {exc}", RssIngestionResult().as_counters()

    try:
        entries = parse_feed(raw, max_entries=MAX_ENTRIES_PER_RUN)
    except FeedParseError as exc:
        logger.warning("rss_parse_failed", source_id=source.id, error=str(exc))
        return "FAILED", f"parse failed: {exc}", RssIngestionResult().as_counters()

    result = RssIngestionResult()
    result.discovered = len(entries)

    for entry in entries:
        try:
            outcome = await _persist_entry(
                db, entry=entry, source=source, organization_id=organization_id, actor_id=actor_id
            )
            if outcome == "created":
                result.created += 1
            else:
                result.duplicates += 1
        except Exception as exc:  # noqa: BLE001 - one bad entry must not sink the run
            logger.warning(
                "rss_entry_persist_failed", source_id=source.id, guid=entry.guid, error=str(exc)
            )
            result.failed += 1
            result.errors.append(f"{entry.guid or entry.title}: {exc}")

    await db.commit()

    if result.discovered == 0:
        return "COMPLETED", None, result.as_counters()
    if result.failed == 0:
        return "COMPLETED", None, result.as_counters()
    if result.created > 0 or result.duplicates > 0:
        return "PARTIAL", "; ".join(result.errors[:5]), result.as_counters()
    return "FAILED", "; ".join(result.errors[:5]), result.as_counters()
