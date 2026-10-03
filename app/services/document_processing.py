import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.config import settings
from app.models.document import RegulatoryDocument, RegulatoryVersion, DocumentProcessingStatus
from app.processing.extraction import extract_text_from_file
from app.ai.service import AIService
from app.services.intelligence_service import persist_intelligence
import structlog

logger = structlog.get_logger()


async def _analyze_with_ai(extracted_text: str, title: str, document_id: str):
    """
    Attempt AI-assisted change/obligation extraction. Returns None, never raises, if AI
    enrichment is disabled or no provider is registered or reachable -- that is an
    expected configuration state here, not a processing failure. Deterministic text
    extraction (the caller) has already succeeded and must not be reported as failed
    just because the optional AI step could not run.
    """
    if not settings.AI_ENRICHMENT_ENABLED:
        logger.info("ai_document_analysis_skipped_disabled", document_id=document_id)
        return None

    try:
        ai_service = AIService()
    except Exception as exc:
        # Most commonly ValueError("No AI providers registered"): a configuration
        # state, not a document-processing failure.
        logger.warning(
            "ai_provider_unavailable", document_id=document_id, error=str(exc)
        )
        return None

    try:
        return await ai_service.analyze_document(
            extracted_text=extracted_text, document_title=title
        )
    except Exception as exc:
        logger.warning(
            "ai_document_analysis_failed", document_id=document_id, error=str(exc)
        )
        return None


async def process_document(document_id: str, db: AsyncSession) -> bool:
    """
    Process a regulatory document: extract text (deterministic), create a version record,
    then attempt optional AI-assisted change/obligation extraction.

    AI is strictly additive here, matching the impact-assessment engine's contract
    (app/matching/engine.py): deterministic text extraction and version tracking complete
    and are persisted regardless of whether AI is enabled, available, or succeeds. A
    document is only ever marked FAILED for a real processing failure (missing storage
    key, extraction error) -- never because no AI provider happened to be registered.
    Returns True if successful, False otherwise.
    """
    try:
        # Get the document
        result = await db.execute(select(RegulatoryDocument).where(RegulatoryDocument.id == document_id))
        document = result.scalars().first()
        if not document:
            logger.error("document_not_found", document_id=document_id)
            return False

        # Update status to PARSING
        document.processing_status = DocumentProcessingStatus.PARSING
        await db.commit()

        # Extract text from the file
        if not document.storage_key:
            logger.error("no_storage_key", document_id=document_id)
            document.processing_status = DocumentProcessingStatus.FAILED
            await db.commit()
            return False

        extracted_text = await extract_text_from_file(document.storage_key, document.mime_type)
        if extracted_text is None:
            logger.error("extraction_failed", document_id=document_id)
            document.processing_status = DocumentProcessingStatus.FAILED
            await db.commit()
            return False

        # Update document with extracted text
        document.extracted_text = extracted_text
        document.parsed_at = datetime.utcnow()
        document.processing_status = DocumentProcessingStatus.PARSED
        await db.commit()

        # Create a version record. This is deterministic document-content tracking,
        # independent of whether AI analysis is enabled, available, or succeeds.
        # Check if there's an existing current version
        existing_version_result = await db.execute(
            select(RegulatoryVersion)
            .where(RegulatoryVersion.document_id == document.id, RegulatoryVersion.is_current == True)
        )
        existing_version = existing_version_result.scalars().first()

        if existing_version:
            # Mark old version as not current
            existing_version.is_current = False
            version_number = existing_version.version_number + 1
        else:
            version_number = 1

        version = RegulatoryVersion(
            id=str(uuid.uuid4()),
            document_id=document.id,
            version_number=version_number,
            sha256=document.sha256,
            content_hash=document.sha256,  # For now, same as file hash
            storage_key=document.storage_key,
            published_at=document.publication_date or datetime.utcnow(),
            is_current=True,
            previous_version_id=existing_version.id if existing_version else None,
        )
        db.add(version)
        await db.commit()  # Commit to get the version ID

        # Optional AI-assisted extraction. Never raises; returns None if AI is
        # disabled, unavailable, or fails, in which case no changes/obligations are
        # invented and the document is not falsely reported as AI-analyzed.
        logger.info("starting_ai_analysis", document_id=document_id)
        analysis_result = await _analyze_with_ai(
            extracted_text=extracted_text, title=document.title, document_id=document_id
        )

        if analysis_result is not None:
            changes_created, obligations_created = await persist_intelligence(
                db=db,
                document_id=document.id,
                version_id=version.id,
                analysis_result=analysis_result,
            )
            logger.info(
                "intelligence_persisted",
                document_id=document_id,
                version_id=version.id,
                changes_count=len(changes_created),
                obligations_count=len(obligations_created),
            )
            document.processing_status = DocumentProcessingStatus.ANALYZED
        else:
            # Text extraction and versioning succeeded; AI analysis did not run or did
            # not succeed. PARSED accurately reflects what was actually done -- it is
            # not relabelled ANALYZED, which would claim an AI pass that never happened.
            logger.info("document_processed_without_ai_analysis", document_id=document_id)
            document.processing_status = DocumentProcessingStatus.PARSED

        await db.commit()

        logger.info("document_processed_successfully", document_id=document_id)
        return True

    except Exception as e:
        logger.error("document_processing_failed", document_id=document_id, error=str(e))
        # Try to update status to FAILED
        try:
            result = await db.execute(select(RegulatoryDocument).where(RegulatoryDocument.id == document_id))
            document = result.scalars().first()
            if document:
                document.processing_status = DocumentProcessingStatus.FAILED
                await db.commit()
        except Exception:
            pass
        return False

async def process_document_background(document_id: str):
    """
    Background task to process a document.
    This is meant to be called from a background worker.
    """
    # Create a new DB session for this background task
    # Note: In production, we'd use a proper background task queue (Celery, RQ, etc.)
    # For now, we'll use the same session factory
    from app.db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await process_document(document_id, db)