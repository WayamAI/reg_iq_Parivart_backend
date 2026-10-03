"""
The smallest safe HTML ingestion adapter: one page, treated deterministically and
uniformly, never a crawler.

Deliberately NOT a general web-scraping adapter. A real per-site scraper needs a
per-source extraction rule (which CSS selector holds the actual notice text on THIS
regulator's page, as opposed to navigation/boilerplate) -- that is a genuine,
source-specific design decision this module does not make or guess at, per the
explicit instruction not to build unresolved policy into an adapter.

What this module does instead: fetch the source's configured url, strip
script/style/nav noise the same way app/processing/extraction.extract_text_from_html
already does for a manually uploaded HTML file, and persist the WHOLE page's visible
text as one document. No link on the page is ever followed; nothing beyond the single
configured url is ever fetched. This is useful for a source whose url already points
directly at a specific notice/page (the common case for a one-off regulatory
announcement), and honest about not being more than that -- it does not claim to
extract only articles vs. extract only navigation, it extracts everything visible and
leaves identifying the substantive part to deterministic matching/human review
downstream, exactly like a manual HTML upload already does today via the same
extraction function.
"""

import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.rss_fetcher import FeedFetchError, fetch_feed
from app.models.document import DocumentProcessingStatus, DocumentType, RegulatoryDocument
from app.models.regulatory import RegulatorySource
from app.processing.extraction import extract_text_from_html
from app.services.audit_service import ENTITY_REGULATORY_DOCUMENT, EVENT_DOCUMENT_UPLOADED, AuditService
from app.services.document_service import check_duplicate_sha256, storage

logger = structlog.get_logger()

HTML_CONTENT_TYPE_MARKERS = ("html",)
MAX_TITLE_LENGTH = 500


def _extract_title(raw_html: bytes) -> Optional[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw_html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()[:MAX_TITLE_LENGTH]
    return None


async def run_html_ingestion(
    db: AsyncSession,
    *,
    source: RegulatorySource,
    organization_id: str,
    actor_id: Optional[str] = None,
) -> tuple[str, Optional[str], dict]:
    """
    Fetch and persist exactly one document from `source.url`.

    Returns (status, error, counters) matching run_rss_ingestion's contract so
    run_source can treat both adapters uniformly. Never raises.
    """
    counters = {
        "documents_discovered": 0,
        "documents_downloaded": 0,
        "documents_processed": 0,
        "documents_failed": 0,
    }

    if not source.url:
        return "FAILED", "source has no url configured", counters

    counters["documents_discovered"] = 1

    try:
        raw_html = await fetch_feed(
            source.url, acceptable_content_type_markers=HTML_CONTENT_TYPE_MARKERS
        )
    except FeedFetchError as exc:
        logger.warning("html_fetch_failed", source_id=source.id, error=str(exc))
        counters["documents_failed"] = 1
        return "FAILED", f"fetch failed: {exc}", counters

    counters["documents_downloaded"] = 1

    try:
        text = await extract_text_from_html(raw_html)
    except Exception as exc:  # noqa: BLE001 - malformed HTML must not crash the run
        logger.warning("html_parse_failed", source_id=source.id, error=str(exc))
        counters["documents_failed"] = 1
        return "FAILED", f"parse failed: {exc}", counters

    if not text.strip():
        counters["documents_failed"] = 1
        return "FAILED", "page had no extractable text content", counters

    title = _extract_title(raw_html) or (source.name or "Untitled HTML Page")
    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    existing = await check_duplicate_sha256(sha256, db, organization_id)
    if existing is not None:
        counters["documents_processed"] = 1
        return "COMPLETED", None, counters

    try:
        storage_key = await storage.upload_file(
            io.BytesIO(text.encode("utf-8")),
            file_name=f"{uuid.uuid4().hex}.txt",
            content_type="text/plain",
        )

        document = RegulatoryDocument(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            authority_id=source.authority_id,
            source_id=source.id,
            title=title,
            document_type=DocumentType.NOTICE,
            jurisdiction=source.jurisdiction,
            country=source.country,
            source_url=source.url,
            storage_key=storage_key,
            mime_type="text/plain",
            file_size=len(text.encode("utf-8")),
            sha256=sha256,
            # The whole page's visible text is already in hand -- nothing further to
            # extract. PARSED, never ANALYZED: no AI analysis ran.
            processing_status=DocumentProcessingStatus.PARSED,
            extracted_text=text,
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
                "title": title,
                "document_type": DocumentType.NOTICE.value,
                "sha256": sha256,
                "authority_id": source.authority_id,
                "source_id": source.id,
                "file_size": document.file_size,
                "ingested_via": "html",
            },
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - a persistence failure must not raise
        logger.warning("html_persist_failed", source_id=source.id, error=str(exc))
        counters["documents_failed"] = 1
        return "FAILED", f"persist failed: {exc}", counters

    counters["documents_processed"] = 1
    return "COMPLETED", None, counters
