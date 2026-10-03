"""
persist_intelligence: obligation-to-change linking.

Obligations used to be persisted with change_id=None unconditionally. These tests cover
the deterministic replacement: link only when the extraction itself gives an unambiguous
basis to do so, and never fabricate a link otherwise.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.future import select

from app.ai.schemas import (
    DocumentAnalysisResult,
    DocumentSummary,
    ExtractedChange,
    ExtractedObligation,
)
from app.db.database import AsyncSessionLocal
from app.models.document import RegulatoryDocument, RegulatoryVersion
from app.models.intelligence import RegulatoryObligation
from app.models.regulatory import ConnectorType, RegulatoryAuthority, RegulatorySource, SourceType
from app.services.intelligence_service import persist_intelligence


async def _document_and_version(session, organization_id: str):
    authority = RegulatoryAuthority(
        id=str(uuid.uuid4()),
        name="Intelligence Test Authority",
        short_name=f"ITA-{uuid.uuid4().hex[:6]}",
        jurisdiction="Testland",
        country="Testland",
        is_active=True,
    )
    session.add(authority)
    await session.flush()

    source = RegulatorySource(
        id=str(uuid.uuid4()),
        authority_id=authority.id,
        name=f"Intelligence Test Source {uuid.uuid4().hex[:6]}",
        jurisdiction=authority.jurisdiction,
        country=authority.country,
        source_type=SourceType.DOCUMENT,
        connector_type=ConnectorType.DOCUMENT,
        enabled=True,
    )
    session.add(source)
    await session.flush()

    document = RegulatoryDocument(
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        authority_id=authority.id,
        source_id=source.id,
        title="Test Document",
        sha256=uuid.uuid4().hex + uuid.uuid4().hex[:32],
    )
    session.add(document)
    await session.flush()

    version = RegulatoryVersion(
        id=str(uuid.uuid4()),
        document_id=document.id,
        version_number=1,
        is_current=True,
    )
    session.add(version)
    await session.flush()

    return document, version


def _analysis(changes, obligations) -> DocumentAnalysisResult:
    return DocumentAnalysisResult(
        document_summary=DocumentSummary(
            title="Test Document",
            document_type="REGULATION",
            jurisdiction="Testland",
            summary="A test summary.",
            key_topics=[],
        ),
        changes=changes,
        obligations=obligations,
        applicability=[],
        confidence=0.8,
        prompt_version="v1",
        ai_model="stub:test",
        analyzed_at=datetime.now(timezone.utc),
    )


def _change(section: str) -> ExtractedChange:
    return ExtractedChange(
        section=section,
        change_type="NEW_REQUIREMENT",
        summary=f"Change in {section}",
        confidence=0.9,
    )


def _obligation(text: str, source_section: str | None) -> ExtractedObligation:
    return ExtractedObligation(
        text=text,
        category="LABELING",
        source_section=source_section,
        confidence=0.9,
    )


async def test_single_change_links_unambiguously(demo_org):
    async with AsyncSessionLocal() as session:
        document, version = await _document_and_version(session, demo_org.id)
        analysis = _analysis(
            changes=[_change("Section 5.2")],
            obligations=[_obligation("Update the label.", source_section=None)],
        )

        changes, obligations = await persist_intelligence(
            db=session, document_id=document.id, version_id=version.id, analysis_result=analysis
        )

        assert len(changes) == 1
        assert len(obligations) == 1
        assert obligations[0].change_id == changes[0].id


async def test_matching_section_links_among_multiple_changes(demo_org):
    async with AsyncSessionLocal() as session:
        document, version = await _document_and_version(session, demo_org.id)
        analysis = _analysis(
            changes=[_change("Section 5.2"), _change("Section 7.1")],
            obligations=[_obligation("Update the label.", source_section="Section 7.1")],
        )

        changes, obligations = await persist_intelligence(
            db=session, document_id=document.id, version_id=version.id, analysis_result=analysis
        )

        matched_change = next(c for c in changes if c.section == "Section 7.1")
        assert obligations[0].change_id == matched_change.id


async def test_ambiguous_section_is_left_unlinked_not_guessed(demo_org):
    async with AsyncSessionLocal() as session:
        document, version = await _document_and_version(session, demo_org.id)
        analysis = _analysis(
            changes=[_change("Section 5.2"), _change("Section 7.1")],
            obligations=[_obligation("Update the label.", source_section="Section 9.9")],
        )

        changes, obligations = await persist_intelligence(
            db=session, document_id=document.id, version_id=version.id, analysis_result=analysis
        )

        assert obligations[0].change_id is None


async def test_no_changes_leaves_obligation_unlinked(demo_org):
    async with AsyncSessionLocal() as session:
        document, version = await _document_and_version(session, demo_org.id)
        analysis = _analysis(
            changes=[],
            obligations=[_obligation("Update the label.", source_section="Section 1.1")],
        )

        changes, obligations = await persist_intelligence(
            db=session, document_id=document.id, version_id=version.id, analysis_result=analysis
        )

        assert changes == []
        assert obligations[0].change_id is None

    async with AsyncSessionLocal() as session:
        stored = (
            await session.execute(
                select(RegulatoryObligation).where(
                    RegulatoryObligation.id == obligations[0].id
                )
            )
        ).scalars().first()
        assert stored.change_id is None
