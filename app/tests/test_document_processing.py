"""
Document processing: deterministic text extraction must survive AI being disabled,
unregistered, or failing. Regression coverage for process_document unconditionally
calling AIService() and analyze_document(), which raised ("No AI providers registered")
and was caught by the function's own broad except-and-mark-FAILED handler -- so a document
whose text was extracted perfectly fine was reported FAILED purely because no AI provider
happened to be registered, which is the normal, default, documented state of this backend.
"""

import io
import uuid

import pytest

from app.ai.base import AIProvider, AIProviderFactory
from app.ai.schemas import DocumentAnalysisResult, DocumentSummary, ExtractedChange, ExtractedObligation
from app.db.database import AsyncSessionLocal
from app.models.document import DocumentProcessingStatus, RegulatoryDocument
from app.models.intelligence import RegulatoryChange, RegulatoryObligation
from app.models.regulatory import ConnectorType, RegulatoryAuthority, RegulatorySource, SourceType
from app.services import document_processing
from app.services.document_processing import process_document
from app.services.document_service import upload_and_create_document
from app.storage.base import LocalStorage


class StubAnalysisProvider(AIProvider):
    """Returns a fixed analysis result instead of calling a real model."""

    def __init__(self, result: DocumentAnalysisResult):
        self.result = result

    @property
    def provider_name(self) -> str:
        return "stub-analysis"

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def generate_structured_output(self, prompt, response_model, **kwargs):
        # AIService.analyze_document makes three calls: summary, changes, obligations.
        if response_model is DocumentSummary:
            return self.result.document_summary
        if response_model == list[ExtractedChange]:
            return self.result.changes
        if response_model == list[ExtractedObligation]:
            return self.result.obligations
        raise AssertionError(f"unexpected response_model: {response_model}")

    async def generate_text(self, prompt, system_prompt=None, temperature=0.1) -> str:
        return ""


async def _uploaded_document(demo_org, tmp_path, monkeypatch, content: bytes = b"A regulatory notice."):
    storage = LocalStorage(base_path=str(tmp_path))
    monkeypatch.setattr("app.services.document_service.storage", storage)
    monkeypatch.setattr("app.processing.extraction.storage", storage)

    async with AsyncSessionLocal() as session:
        authority = RegulatoryAuthority(
            id=str(uuid.uuid4()),
            name="Processing Test Authority",
            short_name=f"PTA-{uuid.uuid4().hex[:6]}",
            jurisdiction="Testland",
            country="Testland",
            is_active=True,
        )
        session.add(authority)
        await session.flush()

        source = RegulatorySource(
            id=str(uuid.uuid4()),
            authority_id=authority.id,
            name=f"Processing Test Source {uuid.uuid4().hex[:6]}",
            jurisdiction=authority.jurisdiction,
            country=authority.country,
            source_type=SourceType.DOCUMENT,
            connector_type=ConnectorType.DOCUMENT,
            enabled=True,
        )
        session.add(source)
        await session.flush()

        document, _ = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=authority.id,
            source_id=source.id,
            file_data=io.BytesIO(content),
            file_name="notice.txt",
            content_type="text/plain",
            title="Processing Test Notice",
        )
        return document.id


async def test_ai_disabled_still_parses_the_document(demo_org, tmp_path, monkeypatch):
    """AI_ENRICHMENT_ENABLED is false by default (app/core/config.py). Processing a
    document must still succeed and leave it PARSED, not FAILED."""
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", False)

    document_id = await _uploaded_document(demo_org, tmp_path, monkeypatch)

    async with AsyncSessionLocal() as session:
        ok = await process_document(document_id, session)
        assert ok is True

    async with AsyncSessionLocal() as session:
        document = await session.get(RegulatoryDocument, document_id)
        assert document.processing_status == DocumentProcessingStatus.PARSED
        assert document.extracted_text == "A regulatory notice."


async def test_ai_enabled_but_no_provider_registered_still_parses(
    demo_org, tmp_path, monkeypatch
):
    """Enabling AI_ENRICHMENT_ENABLED with no provider registered (the real default
    state of AIProviderFactory in this codebase) must not fail the document either."""
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(AIProviderFactory, "_providers", {})

    document_id = await _uploaded_document(demo_org, tmp_path, monkeypatch)

    async with AsyncSessionLocal() as session:
        ok = await process_document(document_id, session)
        assert ok is True

    async with AsyncSessionLocal() as session:
        document = await session.get(RegulatoryDocument, document_id)
        assert document.processing_status == DocumentProcessingStatus.PARSED


async def test_ai_enabled_with_registered_provider_persists_intelligence(
    demo_org, tmp_path, monkeypatch
):
    """The full, working path: a registered provider's extraction is persisted and the
    document is genuinely marked ANALYZED."""
    from datetime import datetime, timezone

    analysis = DocumentAnalysisResult(
        document_summary=DocumentSummary(
            title="Processing Test Notice",
            document_type="REGULATION",
            jurisdiction="Testland",
            summary="A test summary.",
            key_topics=[],
        ),
        changes=[
            ExtractedChange(
                section="Section 1",
                change_type="NEW_REQUIREMENT",
                summary="A new requirement.",
                confidence=0.9,
            )
        ],
        obligations=[
            ExtractedObligation(
                text="Comply with the new requirement.",
                category="LABELING",
                source_section="Section 1",
                confidence=0.9,
            )
        ],
        applicability=[],
        confidence=0.9,
        prompt_version="v1",
        ai_model="stub:test",
        analyzed_at=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", True)
    # AIService() with no explicit provider name resolves get_default_provider(), the
    # first registered provider -- no need to match settings.AI_PROVIDER here.
    monkeypatch.setitem(
        AIProviderFactory._providers, "stub-analysis", StubAnalysisProvider(analysis)
    )

    document_id = await _uploaded_document(demo_org, tmp_path, monkeypatch)

    async with AsyncSessionLocal() as session:
        ok = await process_document(document_id, session)
        assert ok is True

    async with AsyncSessionLocal() as session:
        document = await session.get(RegulatoryDocument, document_id)
        assert document.processing_status == DocumentProcessingStatus.ANALYZED

        from sqlalchemy.future import select

        changes = (
            await session.execute(
                select(RegulatoryChange).where(RegulatoryChange.document_id == document_id)
            )
        ).scalars().all()
        obligations = (
            await session.execute(
                select(RegulatoryObligation).where(
                    RegulatoryObligation.document_id == document_id
                )
            )
        ).scalars().all()

        assert len(changes) == 1
        assert len(obligations) == 1
        assert obligations[0].change_id == changes[0].id
