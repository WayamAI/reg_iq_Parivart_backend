"""
The smallest safe API/WEB_SERVICE ingestion adapter: one JSON endpoint, treated
deterministically and uniformly, never a crawler.

RegulatorySource has exactly one configuration field across every source type --
`url` -- so there is nowhere to record a per-source field-mapping (e.g. "the document
text lives at response['items'][0]['body']"). Building that extraction logic in would
mean guessing at an unresolved, source-specific policy. Instead, mirroring how
app/ingestion/html_adapter.py handles the identical constraint: fetch the single
configured url, and persist the WHOLE JSON response as one document -- using a
recognizable text-ish key if the top-level object has one, otherwise the formatted
JSON itself, so nothing is ever silently dropped. Nothing beyond the single configured
url is ever fetched, and this adapter does not follow any link or ref found in the
response.

Covers both SourceType.API and SourceType.WEB_SERVICE -- the source model gives no way
to tell them apart, so one implementation serves both.
"""

import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.rss_fetcher import FeedFetchError, fetch_feed
from app.models.document import DocumentProcessingStatus, DocumentType, RegulatoryDocument
from app.models.regulatory import RegulatorySource
from app.services.audit_service import ENTITY_REGULATORY_DOCUMENT, EVENT_DOCUMENT_UPLOADED, AuditService
from app.services.document_service import check_duplicate_sha256, storage

logger = structlog.get_logger()

API_CONTENT_TYPE_MARKERS = ("json",)
MAX_TITLE_LENGTH = 500
TEXT_KEYS = ("title", "content", "body", "text", "description")


def _extract_content(payload) -> str:
    if isinstance(payload, dict):
        for key in TEXT_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return json.dumps(payload, indent=2, sort_keys=True)


async def run_api_ingestion(
    db: AsyncSession,
    *,
    source: RegulatorySource,
    organization_id: str,
    actor_id: Optional[str] = None,
) -> tuple[str, Optional[str], dict]:
    """
    Fetch and persist exactly one document from `source.url`'s JSON response.

    Returns (status, error, counters) matching run_html_ingestion's contract so
    run_source can treat every adapter uniformly. Never raises.
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
        raw = await fetch_feed(source.url, acceptable_content_type_markers=API_CONTENT_TYPE_MARKERS)
    except FeedFetchError as exc:
        logger.warning("api_fetch_failed", source_id=source.id, error=str(exc))
        counters["documents_failed"] = 1
        return "FAILED", f"fetch failed: {exc}", counters

    counters["documents_downloaded"] = 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("api_parse_failed", source_id=source.id, error=str(exc))
        counters["documents_failed"] = 1
        return "FAILED", f"invalid JSON response: {exc}", counters

    content = _extract_content(payload)
    title = (source.name or "Untitled API Source")[:MAX_TITLE_LENGTH]
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

    existing = await check_duplicate_sha256(sha256, db, organization_id)
    if existing is not None:
        counters["documents_processed"] = 1
        return "COMPLETED", None, counters

    try:
        storage_key = await storage.upload_file(
            io.BytesIO(content.encode("utf-8")),
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
            file_size=len(content.encode("utf-8")),
            sha256=sha256,
            # The response's content is already in hand -- nothing further to
            # extract. PARSED, never ANALYZED: no AI analysis ran.
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
                "title": title,
                "document_type": DocumentType.NOTICE.value,
                "sha256": sha256,
                "authority_id": source.authority_id,
                "source_id": source.id,
                "file_size": document.file_size,
                "ingested_via": "api",
            },
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - a persistence failure must not raise
        logger.warning("api_persist_failed", source_id=source.id, error=str(exc))
        counters["documents_failed"] = 1
        return "FAILED", f"persist failed: {exc}", counters

    counters["documents_processed"] = 1
    return "COMPLETED", None, counters
