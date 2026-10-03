"""
The synthetic regulatory demo document (docs/demo-document/) must actually be
uploadable and processable through the REAL production pipeline, not merely a
well-formed .docx in isolation. This is end-to-end processing verification, distinct
from the earlier structural/XSD validation performed when the file was authored.

Also cross-checks that the .docx and its Markdown source carry the same section
structure, and that neither file contains anything that looks like a credential.
"""

import io
import re
import uuid
import zipfile
from pathlib import Path

import pytest

from app.db.database import AsyncSessionLocal
from app.models.document import DocumentProcessingStatus, RegulatoryDocument
from app.models.regulatory import ConnectorType, RegulatoryAuthority, RegulatorySource, SourceType
from app.services import document_processing
from app.services.document_processing import process_document
from app.services.document_service import upload_and_create_document
from app.storage.base import LocalStorage

DEMO_DIR = Path(__file__).resolve().parents[2] / "docs" / "demo-document"
DOCX_PATH = DEMO_DIR / "PARIVART_Demo_Regulatory_Notice.docx"
MD_PATH = DEMO_DIR / "REGULATORY_DEMO_DOCUMENT.md"

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

CREDENTIAL_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{10,}"),
    re.compile(r"ollama_[A-Za-z0-9]{10,}"),
]


def _docx_text() -> str:
    z = zipfile.ZipFile(DOCX_PATH)
    xml = z.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def test_demo_files_exist():
    assert DOCX_PATH.exists(), f"missing {DOCX_PATH}"
    assert MD_PATH.exists(), f"missing {MD_PATH}"


def test_no_file_contains_anything_that_looks_like_a_credential():
    for path in (DOCX_PATH, MD_PATH):
        content = _docx_text() if path == DOCX_PATH else path.read_text(encoding="utf-8")
        for pattern in CREDENTIAL_PATTERNS:
            assert not pattern.search(content), f"possible credential-like string in {path}"


def test_docx_and_markdown_share_the_same_section_numbers_and_titles():
    md_headings = re.findall(r"^## (\d+\. .+)$", MD_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    docx_text = _docx_text()

    assert len(md_headings) == 9
    for heading in md_headings:
        # The docx paragraph text for a heading runs straight into the next paragraph's
        # text with no separator (plain XML-tag stripping), so a prefix match is the
        # correct check here, not an exact line match.
        assert heading[:40] in docx_text, f"heading not found in docx: {heading}"


def test_docx_discloses_its_fictional_nature_prominently():
    text = _docx_text()
    assert "SYNTHETIC DEMONSTRATION DOCUMENT" in text
    assert "NOT A REAL REGULATION" in text
    assert "not legal advice" in text.lower()
    assert "not affiliated with any real regulator" in text.lower()
    # Both the opening and closing banners are present (the warning is repeated, not a
    # single easy-to-miss disclaimer).
    assert text.count("fictional") >= 10


async def test_demo_docx_processes_through_the_real_pipeline(
    demo_org, tmp_path, monkeypatch
):
    """
    Upload the real demo .docx through upload_and_create_document and run it through
    the real process_document, exactly as a user would via POST /regulatory/documents/
    upload and POST /{id}/process. AI is left disabled (the suite's default), so this
    exercises the deterministic extraction path end to end.
    """
    storage = LocalStorage(base_path=str(tmp_path))
    monkeypatch.setattr("app.services.document_service.storage", storage)
    monkeypatch.setattr("app.processing.extraction.storage", storage)
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", False)

    async with AsyncSessionLocal() as session:
        authority = RegulatoryAuthority(
            id=str(uuid.uuid4()),
            name="Demo Pipeline Test Authority",
            short_name=f"DPTA-{uuid.uuid4().hex[:6]}",
            jurisdiction="Testland",
            country="Testland",
            is_active=True,
        )
        session.add(authority)
        await session.flush()

        source = RegulatorySource(
            id=str(uuid.uuid4()),
            authority_id=authority.id,
            name=f"Demo Pipeline Test Source {uuid.uuid4().hex[:6]}",
            jurisdiction=authority.jurisdiction,
            country=authority.country,
            source_type=SourceType.DOCUMENT,
            connector_type=ConnectorType.DOCUMENT,
            enabled=True,
        )
        session.add(source)
        await session.flush()

        with open(DOCX_PATH, "rb") as f:
            file_bytes = f.read()

        document, is_duplicate = await upload_and_create_document(
            db=session,
            organization_id=demo_org.id,
            authority_id=authority.id,
            source_id=source.id,
            file_data=io.BytesIO(file_bytes),
            file_name="PARIVART_Demo_Regulatory_Notice.docx",
            content_type=DOCX_MIME,
            title="PARIVART Demo Regulatory Notice (Synthetic)",
        )
        assert is_duplicate is False
        document_id = document.id

    async with AsyncSessionLocal() as session:
        ok = await process_document(document_id, session)
        assert ok is True

    async with AsyncSessionLocal() as session:
        document = await session.get(RegulatoryDocument, document_id)
        # AI disabled -> deterministic extraction only -> PARSED, not ANALYZED, and
        # definitely not FAILED.
        assert document.processing_status == DocumentProcessingStatus.PARSED
        assert document.extracted_text is not None
        assert "SYNTHETIC DEMONSTRATION DOCUMENT" in document.extracted_text
        assert "FADDR-DEMO-2026-0147" in document.extracted_text
        assert "Asterion PulseSense" in document.extracted_text
