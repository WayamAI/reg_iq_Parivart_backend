"""
Impact Delta Report generation.

A report makes the whole chain legible and auditable:

    WHAT CHANGED
      -> WHAT OBLIGATION RESULTED
      -> WHAT THE ORGANIZATION OWNS/OPERATES
      -> WHAT IS POTENTIALLY AFFECTED
      -> WHY IT IS AFFECTED
      -> WHAT ACTION MAY BE REQUIRED

Everything in the report is read back from persisted records. Where a fact cannot be
determined from the data, the report says UNKNOWN or UNASSESSED rather than inventing one.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.models.document import RegulatoryDocument
from app.services.audit_service import (
    ENTITY_IMPACT_REPORT,
    EVENT_REPORT_GENERATED,
    AuditService,
)
from app.models.impact import (
    AIEnrichmentStatus,
    EntityType,
    ImpactAssessment,
    ImpactReport,
    ImpactReportStatus,
)
from app.models.intelligence import ObligationCategory, RegulatoryChange, RegulatoryObligation
from app.models.portfolio import Control, Market, Process, Product, Registration
from app.models.regulatory import RegulatoryAuthority

logger = structlog.get_logger()

UNKNOWN = "UNKNOWN"

# What a reviewer may need to do, keyed by the obligation categories that actually matched.
# A category with no entry contributes no action rather than a generic filler one.
ACTION_BY_OBLIGATION_CATEGORY: Dict[ObligationCategory, str] = {
    ObligationCategory.LABELING: "Review affected product labeling and instructions for use against the new requirement.",
    ObligationCategory.PACKAGING: "Review packaging artwork and specifications against the new requirement.",
    ObligationCategory.MANUFACTURING: "Assess manufacturing procedures and validated processes for required changes.",
    ObligationCategory.QUALITY: "Assess quality management system procedures and records for required changes.",
    ObligationCategory.SAFETY: "Review risk management file and safety reporting procedures.",
    ObligationCategory.REPORTING: "Confirm reporting timelines and formats meet the revised requirement.",
    ObligationCategory.REGISTRATION: "Verify affected market registrations remain valid under the revised requirement.",
    ObligationCategory.SUBMISSION: "Determine whether a regulatory submission or notification is required.",
    ObligationCategory.POST_MARKET: "Review post-market surveillance plan and vigilance procedures.",
    ObligationCategory.CLINICAL: "Assess clinical evaluation documentation for required updates.",
    ObligationCategory.DATA: "Review data handling and retention practices against the requirement.",
    ObligationCategory.CYBERSECURITY: "Assess software and device cybersecurity controls against the requirement.",
    ObligationCategory.RECORDKEEPING: "Confirm recordkeeping practices satisfy the revised requirement.",
}

_ENTITY_MODELS = {
    EntityType.PRODUCT: Product,
    EntityType.MARKET: Market,
    EntityType.PROCESS: Process,
    EntityType.CONTROL: Control,
    EntityType.REGISTRATION: Registration,
}


def _enum_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(getattr(value, "value", value))


class ReportService:
    @staticmethod
    async def generate_delta_report(
        db: AsyncSession,
        organization_id: str,
        impact_assessment_id: str,
        title: str = None,
        actor_id: str = None,
    ) -> ImpactReport:
        """
        Generate a versioned, auditable Impact Delta Report for an ImpactAssessment.

        `actor_id` is recorded on the audit trail: a report is a document someone
        produced, and the trail should say who.
        """
        result = await db.execute(
            select(ImpactAssessment)
            .options(selectinload(ImpactAssessment.items))
            .where(
                ImpactAssessment.id == impact_assessment_id,
                ImpactAssessment.organization_id == organization_id,
            )
        )
        assessment = result.scalars().first()
        if not assessment:
            raise ValueError(f"ImpactAssessment {impact_assessment_id} not found")

        change, document, authority = await ReportService._load_regulatory_context(
            db, assessment.regulatory_change_id
        )
        obligations = await ReportService._load_obligations(db, change, document)
        entity_names = await ReportService._resolve_entity_names(
            db, organization_id, assessment.items
        )

        report_payload = {
            "FACT": ReportService._fact_section(document, authority),
            "SOURCE_EVIDENCE": ReportService._evidence_section(change),
            "RESULTING_OBLIGATIONS": ReportService._obligations_section(obligations),
            "SYSTEM_INTERPRETATION": ReportService._interpretation_section(
                assessment, entity_names
            ),
            "AI_ENRICHMENT": ReportService._ai_section(assessment),
            "HUMAN_DECISION": ReportService._human_decision_section(
                obligations, assessment
            ),
        }

        latest = await db.execute(
            select(ImpactReport)
            .where(
                ImpactReport.organization_id == organization_id,
                ImpactReport.impact_assessment_id == impact_assessment_id,
            )
            .order_by(ImpactReport.version.desc())
        )
        previous = latest.scalars().first()

        change_label = change.summary[:60] if change and change.summary else "Regulatory Change"
        report = ImpactReport(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            impact_assessment_id=impact_assessment_id,
            regulatory_change_id=assessment.regulatory_change_id,
            title=title or f"Impact Delta Report: {change_label}",
            summary=assessment.summary,
            status=ImpactReportStatus.GENERATED,
            version=(previous.version + 1) if previous else 1,
            report_data=json.dumps(report_payload),
        )
        db.add(report)
        AuditService.record(
            db,
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=EVENT_REPORT_GENERATED,
            entity_type=ENTITY_IMPACT_REPORT,
            entity_id=report.id,
            payload={
                "impact_assessment_id": impact_assessment_id,
                "version": report.version,
                "supersedes_version": previous.version if previous else None,
            },
        )
        await db.commit()
        await db.refresh(report)
        return report

    # ------------------------------------------------------------------ loading

    @staticmethod
    async def _load_regulatory_context(db: AsyncSession, regulatory_change_id: str):
        change = (
            await db.execute(
                select(RegulatoryChange).where(RegulatoryChange.id == regulatory_change_id)
            )
        ).scalars().first()

        document = None
        if change is not None and change.document_id:
            document = (
                await db.execute(
                    select(RegulatoryDocument).where(
                        RegulatoryDocument.id == change.document_id
                    )
                )
            ).scalars().first()

        authority = None
        if document is not None and document.authority_id:
            authority = (
                await db.execute(
                    select(RegulatoryAuthority).where(
                        RegulatoryAuthority.id == document.authority_id
                    )
                )
            ).scalars().first()

        return change, document, authority

    @staticmethod
    async def _load_obligations(db: AsyncSession, change, document) -> List[RegulatoryObligation]:
        if change is None:
            return []
        obligations = list(
            (
                await db.execute(
                    select(RegulatoryObligation).where(
                        RegulatoryObligation.change_id == change.id
                    )
                )
            ).scalars().all()
        )
        if obligations or document is None:
            return obligations
        return list(
            (
                await db.execute(
                    select(RegulatoryObligation).where(
                        RegulatoryObligation.document_id == document.id
                    )
                )
            ).scalars().all()
        )

    @staticmethod
    async def _resolve_entity_names(
        db: AsyncSession, organization_id: str, items
    ) -> Dict[str, str]:
        """Turn opaque entity_ids into the names the organization actually uses."""
        by_type: Dict[EntityType, List[str]] = {}
        for item in items:
            try:
                entity_type = EntityType(_enum_value(item.entity_type))
            except ValueError:
                continue
            by_type.setdefault(entity_type, []).append(item.entity_id)

        names: Dict[str, str] = {}
        for entity_type, ids in by_type.items():
            model = _ENTITY_MODELS.get(entity_type)
            if model is None:
                continue
            rows = (
                await db.execute(
                    select(model).where(
                        model.id.in_(ids), model.organization_id == organization_id
                    )
                )
            ).scalars().all()
            for row in rows:
                names[row.id] = getattr(row, "name", None) or getattr(
                    row, "registration_number", None
                ) or row.id
        return names

    # ----------------------------------------------------------------- sections

    @staticmethod
    def _fact_section(document, authority) -> Dict[str, Any]:
        """WHAT CHANGED -- the publication facts, verbatim from the stored document."""
        return {
            "title": "Regulatory Publication Facts",
            "document_title": document.title if document else UNKNOWN,
            "authority": (authority.name if authority else UNKNOWN),
            "authority_short_name": (authority.short_name if authority else UNKNOWN),
            "jurisdiction": (
                (document.jurisdiction if document else None)
                or (authority.jurisdiction if authority else None)
                or UNKNOWN
            ),
            "country": (
                (document.country if document else None)
                or (authority.country if authority else None)
                or UNKNOWN
            ),
            "publication_date": str(document.publication_date) if document and document.publication_date else UNKNOWN,
            "effective_date": str(document.effective_date) if document and document.effective_date else UNKNOWN,
            "document_type": _enum_value(document.document_type) if document else UNKNOWN,
            "source_url": (document.source_url if document else None),
            "sha256": (document.sha256 if document else None),
        }

    @staticmethod
    def _evidence_section(change) -> Dict[str, Any]:
        """The citable extract the assessment was built from."""
        if change is None:
            return {"title": "Source Citations & Extracted Changes", "status": "UNASSESSED"}
        return {
            "title": "Source Citations & Extracted Changes",
            "change_summary": change.summary,
            "change_type": _enum_value(change.change_type),
            "section_reference": change.section or UNKNOWN,
            "source_reference": change.source_reference or UNKNOWN,
            "previous_text": change.previous_text,
            "new_text": change.new_text,
        }

    @staticmethod
    def _obligations_section(obligations) -> Dict[str, Any]:
        """WHAT OBLIGATION RESULTED from the change."""
        if not obligations:
            return {
                "title": "Resulting Obligations",
                "status": "UNASSESSED",
                "note": "No obligations have been extracted for this change.",
                "obligations": [],
            }
        return {
            "title": "Resulting Obligations",
            "status": "ASSESSED",
            "obligations": [
                {
                    "id": o.id,
                    "text": o.text,
                    "category": _enum_value(o.category),
                    "applicability": o.applicability or UNKNOWN,
                    "jurisdiction": o.jurisdiction or UNKNOWN,
                    "effective_date": str(o.effective_date) if o.effective_date else UNKNOWN,
                    "source_section": o.source_section or UNKNOWN,
                    "source_page": o.source_page or UNKNOWN,
                }
                for o in obligations
            ],
        }

    @staticmethod
    def _interpretation_section(assessment, entity_names) -> Dict[str, Any]:
        """WHAT IS AFFECTED and WHY -- one entry per deterministic impact item."""
        affected = []
        for item in assessment.items:
            try:
                evidence = json.loads(item.evidence) if item.evidence else {}
            except (TypeError, ValueError):
                evidence = {}
            affected.append(
                {
                    "entity_type": _enum_value(item.entity_type),
                    "entity_id": item.entity_id,
                    "entity_name": entity_names.get(item.entity_id, UNKNOWN),
                    "obligation_id": item.obligation_id,
                    "impact_level": _enum_value(item.impact_level),
                    "confidence": float(item.confidence) if item.confidence is not None else None,
                    "match_score": float(item.match_score) if item.match_score is not None else None,
                    "match_types": (item.match_types or "").split(",") if item.match_types else [],
                    "why_affected": item.reason,
                    "evidence": evidence,
                }
            )
        return {
            "title": "Deterministic Impact Assessment",
            "overall_impact_level": _enum_value(assessment.overall_impact_level),
            "overall_confidence": (
                float(assessment.overall_confidence)
                if assessment.overall_confidence is not None
                else None
            ),
            "summary": assessment.summary,
            "affected_portfolio_count": len(affected),
            "affected_items": affected,
            "engine_version": assessment.engine_version,
            "analysis_version": assessment.analysis_version,
        }

    @staticmethod
    def _ai_section(assessment) -> Dict[str, Any]:
        """
        Makes it unambiguous whether any AI contributed. The deterministic assessment
        above stands on its own regardless of what this says.
        """
        status = _enum_value(assessment.ai_enrichment_status) or AIEnrichmentStatus.DISABLED.value
        return {
            "title": "Optional AI Enrichment",
            "status": status,
            "error": assessment.ai_enrichment_error,
            "narrative": assessment.ai_narrative,
            "ai_model": assessment.ai_model,
            "prompt_version": assessment.prompt_version,
            "note": (
                "AI narrative present."
                if status == AIEnrichmentStatus.SUCCESS.value
                else "No AI narrative. The assessment above is fully deterministic."
            ),
        }

    @staticmethod
    def _human_decision_section(obligations, assessment) -> Dict[str, Any]:
        """
        WHAT ACTION MAY BE REQUIRED -- derived strictly from the obligation categories
        that actually matched. No obligations, or no mapped category, means UNASSESSED.
        """
        matched_obligation_ids = {
            item.obligation_id for item in assessment.items if item.obligation_id
        }
        relevant = [o for o in obligations if o.id in matched_obligation_ids] or obligations

        actions = []
        for obligation in relevant:
            try:
                category = ObligationCategory(_enum_value(obligation.category))
            except ValueError:
                continue
            action = ACTION_BY_OBLIGATION_CATEGORY.get(category)
            if action and action not in [a["action"] for a in actions]:
                actions.append(
                    {
                        "action": action,
                        "derived_from_obligation_id": obligation.id,
                        "obligation_category": category.value,
                    }
                )

        return {
            "title": "Human Review Decision & Required Action",
            "status": "REQUIRES_HUMAN_REVIEW" if actions else "UNASSESSED",
            "note": (
                None
                if actions
                else "No action could be derived from the available data. A reviewer must "
                "determine what, if anything, is required."
            ),
            "recommended_actions": actions,
            "reviewer_notes": None,
            "decision": None,
            "reviewed_by": None,
            "reviewed_at": None,
        }
