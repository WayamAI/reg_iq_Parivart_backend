import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.intelligence import RegulatoryChange, RegulatoryObligation, ChangeType, ObligationCategory
from app.models.document import RegulatoryDocument, RegulatoryVersion
from app.ai.schemas import DocumentAnalysisResult, ExtractedChange, ExtractedObligation
import structlog

logger = structlog.get_logger()


def _match_obligation_to_change(
    obligation_data: ExtractedObligation, changes: list[RegulatoryChange]
) -> str | None:
    """
    Deterministically match an extracted obligation to one of this document's extracted
    changes, using only the data the extraction itself provided.

    Unambiguous cases only:
      - Exactly one change was extracted for the document -> that change caused it.
      - The obligation's source_section matches exactly one change's section
        (case-insensitive) -> that change caused it.

    Anything else (no changes, no section given, or the section matches zero or more than
    one change) returns None rather than guessing -- a fabricated link would misrepresent
    provenance that the product's audit/evidence story depends on.
    """
    if not changes:
        return None
    if len(changes) == 1:
        return changes[0].id

    section = (obligation_data.source_section or "").strip().lower()
    if not section:
        return None

    matches = [
        change
        for change in changes
        if (change.section or "").strip().lower() == section
    ]
    if len(matches) == 1:
        return matches[0].id
    return None


async def persist_intelligence(
    db: AsyncSession,
    document_id: str,
    version_id: str,
    analysis_result: DocumentAnalysisResult,
) -> tuple[list[RegulatoryChange], list[RegulatoryObligation]]:
    """
    Persist the extracted changes and obligations from the AI analysis.
    Returns the lists of created changes and obligations.
    """
    changes_created = []
    obligations_created = []

    # Persist changes
    for change_data in analysis_result.changes:
        # Validate change_type
        try:
            change_type_enum = ChangeType(change_data.change_type)
        except ValueError:
            logger.warning("invalid_change_type: %s", change_data.change_type)
            change_type_enum = ChangeType.OTHER

        change = RegulatoryChange(
            id=str(uuid.uuid4()),
            document_id=document_id,
            version_id=version_id,
            section=change_data.section,
            change_type=change_type_enum,
            summary=change_data.summary,
            previous_text=change_data.previous_text,
            new_text=change_data.new_text,
            source_reference=change_data.source_reference,
            confidence=change_data.confidence,
            prompt_version=analysis_result.prompt_version,
            ai_model=analysis_result.ai_model,
        )
        db.add(change)
        changes_created.append(change)

    # Persist obligations
    for obligation_data in analysis_result.obligations:
        try:
            obligation_category_enum = ObligationCategory(obligation_data.category)
        except ValueError:
            logger.warning("invalid_obligation_category: %s", obligation_data.category)
            obligation_category_enum = ObligationCategory.OTHER

        obligation = RegulatoryObligation(
            id=str(uuid.uuid4()),
            change_id=_match_obligation_to_change(obligation_data, changes_created),
            document_id=document_id,
            text=obligation_data.text,
            category=obligation_category_enum,
            applicability=obligation_data.applicability,
            jurisdiction=obligation_data.jurisdiction,
            effective_date=obligation_data.effective_date,
            source_page=obligation_data.source_page,
            source_section=obligation_data.source_section,
            confidence=obligation_data.confidence,
            prompt_version=analysis_result.prompt_version,
            ai_model=analysis_result.ai_model,
        )
        db.add(obligation)
        obligations_created.append(obligation)

    # Commit all changes
    await db.commit()

    # Refresh to get IDs and any defaults
    for change in changes_created:
        await db.refresh(change)
    for obligation in obligations_created:
        await db.refresh(obligation)

    return changes_created, obligations_created