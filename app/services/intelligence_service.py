from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.intelligence import RegulatoryChange, RegulatoryObligation, ChangeType, ObligationCategory
from app.models.document import RegulatoryDocument, RegulatoryVersion
from app.ai.schemas import DocumentAnalysisResult, ExtractedChange, ExtractedObligation
import structlog

logger = structlog.get_logger()

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
            logger.warning("invalid_change_type", change_type=change_data.change_type, defaulting_to_OTHER)
            change_type_enum = ChangeType.OTHER

        change = RegulatoryChange(
            id=str(__import__('uuid').uuid4()),
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
            logger.warning("invalid_obligation_category", category=obligation_data.category, defaulting_to_OTHER)
            obligation_category_enum = ObligationCategory.OTHER

        obligation = RegulatoryObligation(
            id=str(__import__('uuid').uuid4()),
            change_id=None,  # We don't have a change_id yet; we'll set it later if we want to link obligations to changes.
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

async def link_obligations_to_changes(
    db: AsyncSession,
    document_id: str,
) -> None:
    """
    After changes and obligations are created, we can try to link obligations to changes.
    This is a simple heuristic: for each obligation, find a change in the same document that has overlapping text or proximity.
    For now, we'll skip this and leave change_id as NULL. In a future implementation, we might do more sophisticated linking.
    """
    # For now, we do nothing.
    pass