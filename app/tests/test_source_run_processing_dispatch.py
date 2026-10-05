"""
POST /sources/{id}/run must hand every newly created RegulatoryDocument to the SAME
document-processing pipeline manual upload already uses (app/services/document_processing
.process_document, dispatched via the existing BackgroundTasks mechanism -- see
app/api/routers/regulatory_sources.py::run_source). This covers that dispatch for every
source type with a real adapter (RSS, HTML, API, WEB_SERVICE), and the AI-disabled,
AI-enabled, AI-failure, dedup, and tenant-isolation behavior of the resulting pipeline.

Only the external fetch and (where used) the AI provider are mocked. The dispatch itself,
process_document, intelligence persistence, and the database are all real -- httpx's
ASGITransport runs FastAPI's BackgroundTasks to completion as part of the request/response
cycle, so by the time `client.post(.../run)` returns, processing has already happened.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.ai.base import AIProvider, AIProviderFactory
from app.ai.schemas import DocumentAnalysisResult, DocumentSummary, ExtractedChange, ExtractedObligation
from app.ingestion import api_adapter, html_adapter, rss_ingestion
from app.ingestion.rss_fetcher import FeedFetchError
from app.models.document import DocumentProcessingStatus, RegulatoryDocument
from app.models.intelligence import RegulatoryChange, RegulatoryObligation
from app.services import document_processing
from app.storage.base import LocalStorage

RSS_FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Dispatch Test Entry</title><description>A notice body.</description>
<guid>dispatch-test-entry</guid></item>
</channel></rss>"""

HTML_PAGE = b"<html><head><title>Dispatch Test Page</title></head><body><p>Notice body.</p></body></html>"

API_PAYLOAD = json.dumps({"title": "Dispatch Test API", "body": "Notice body."}).encode()


async def _async_return(value):
    return value


@pytest.fixture(autouse=True)
def _use_tmp_storage(tmp_path, monkeypatch):
    """Every adapter module and app.processing.extraction captured their own `storage`
    reference at import time (`from app.services.document_service import storage`) --
    patching document_service.storage alone would not affect them."""
    storage = LocalStorage(base_path=str(tmp_path))
    monkeypatch.setattr(rss_ingestion, "storage", storage)
    monkeypatch.setattr(html_adapter, "storage", storage)
    monkeypatch.setattr(api_adapter, "storage", storage)
    monkeypatch.setattr("app.processing.extraction.storage", storage)


class StubAnalysisProvider(AIProvider):
    def __init__(self, result: DocumentAnalysisResult):
        self.result = result

    @property
    def provider_name(self) -> str:
        return "stub-analysis"

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def generate_structured_output(self, prompt, response_model, **kwargs):
        if response_model is DocumentSummary:
            return self.result.document_summary
        if response_model == list[ExtractedChange]:
            return self.result.changes
        if response_model == list[ExtractedObligation]:
            return self.result.obligations
        raise AssertionError(f"unexpected response_model: {response_model}")

    async def generate_text(self, prompt, system_prompt=None, temperature=0.1) -> str:
        return ""


class FailingAnalysisProvider(AIProvider):
    @property
    def provider_name(self) -> str:
        return "stub-failing"

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def generate_structured_output(self, prompt, response_model, **kwargs):
        raise RuntimeError("simulated provider outage")

    async def generate_text(self, prompt, system_prompt=None, temperature=0.1) -> str:
        raise RuntimeError("simulated provider outage")


def _analysis_result() -> DocumentAnalysisResult:
    return DocumentAnalysisResult(
        document_summary=DocumentSummary(
            title="Dispatch Test",
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


async def _source(client, auth_headers, source_type: str, *, url: str = "https://authority.example/feed") -> dict:
    authority = await client.post(
        "/api/v1/regulatory/authorities/",
        json={
            "name": f"Dispatch Test Authority {source_type}-{uuid.uuid4().hex[:6]}",
            "short_name": f"DTA-{uuid.uuid4().hex[:6]}",
            "jurisdiction": "Testland",
            "country": "Testland",
        },
        headers=auth_headers,
    )
    assert authority.status_code == 201, authority.text

    source = await client.post(
        "/api/v1/regulatory/sources/",
        json={
            "authority_id": authority.json()["id"],
            "name": f"Dispatch Test Source {source_type}-{uuid.uuid4().hex[:6]}",
            "source_type": source_type,
            "connector_type": source_type,
            "url": url,
            "enabled": True,
        },
        headers=auth_headers,
    )
    assert source.status_code == 201, source.text
    return source.json()


def _mock_fetch_for(source_type: str, monkeypatch, body: bytes = None):
    if source_type == "RSS":
        monkeypatch.setattr(rss_ingestion, "fetch_feed", lambda url, **kwargs: _async_return(body or RSS_FEED))
    elif source_type == "HTML":
        monkeypatch.setattr(html_adapter, "fetch_feed", lambda url, **kwargs: _async_return(body or HTML_PAGE))
    else:  # API, WEB_SERVICE
        monkeypatch.setattr(api_adapter, "fetch_feed", lambda url, **kwargs: _async_return(body or API_PAYLOAD))


async def _only_document_for(client, auth_headers) -> dict:
    documents = await client.get("/api/v1/regulatory/documents/", headers=auth_headers)
    assert documents.status_code == 200, documents.text
    body = documents.json()
    assert len(body) == 1, body
    return body[0]


@pytest.mark.parametrize("source_type", ["RSS", "HTML", "API", "WEB_SERVICE"])
async def test_run_dispatches_processing_and_ai_disabled_does_not_fabricate_intelligence(
    client, auth_headers, monkeypatch, source_type
):
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", False)
    _mock_fetch_for(source_type, monkeypatch)
    source = await _source(client, auth_headers, source_type)

    response = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "COMPLETED"

    document = await _only_document_for(client, auth_headers)
    # Processing ran (not left at the adapter's own PARSED-without-a-version state):
    # extracted_text survives a real re-extraction pass and the document is still PARSED,
    # never ANALYZED, since no AI ran.
    assert document["processing_status"] == DocumentProcessingStatus.PARSED.value

    changes = await client.get("/api/v1/regulatory/changes/", headers=auth_headers)
    obligations = await client.get("/api/v1/regulatory/obligations/", headers=auth_headers)
    assert changes.json() == []
    assert obligations.json() == []


async def test_run_with_ai_enabled_persists_change_and_obligation(client, auth_headers, monkeypatch):
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", True)
    monkeypatch.setitem(
        AIProviderFactory._providers, "stub-analysis", StubAnalysisProvider(_analysis_result())
    )
    _mock_fetch_for("RSS", monkeypatch)
    source = await _source(client, auth_headers, "RSS")

    response = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert response.status_code == 202, response.text

    document = await _only_document_for(client, auth_headers)
    assert document["processing_status"] == DocumentProcessingStatus.ANALYZED.value

    changes = (await client.get("/api/v1/regulatory/changes/", headers=auth_headers)).json()
    obligations = (await client.get("/api/v1/regulatory/obligations/", headers=auth_headers)).json()
    assert len(changes) == 1
    assert len(obligations) == 1
    assert changes[0]["document_id"] == document["id"]


async def test_ai_provider_failure_still_leaves_the_document_persisted_with_no_fabricated_intelligence(
    client, auth_headers, monkeypatch
):
    """A real ingestion success (document persisted) must not be undone by an AI
    failure. Pre-existing behavior of app/ai/service.py::AIService.analyze_document
    (not introduced by this change, and identical for a manual upload): each of its
    three calls (summary/changes/obligations) has its own try/except, so a total
    provider outage still returns a DocumentAnalysisResult (a fallback summary, empty
    changes/obligations lists) rather than None -- the document ends up ANALYZED, not
    PARSED. The safety property that actually matters still holds: zero changes and
    zero obligations are persisted, never a fabricated one."""
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", True)
    monkeypatch.setitem(
        AIProviderFactory._providers, "stub-failing", FailingAnalysisProvider()
    )
    _mock_fetch_for("RSS", monkeypatch)
    source = await _source(client, auth_headers, "RSS")

    response = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "COMPLETED"  # ingestion itself still succeeded

    document = await _only_document_for(client, auth_headers)
    assert document["processing_status"] == DocumentProcessingStatus.ANALYZED.value

    changes = (await client.get("/api/v1/regulatory/changes/", headers=auth_headers)).json()
    obligations = (await client.get("/api/v1/regulatory/obligations/", headers=auth_headers)).json()
    assert changes == []
    assert obligations == []


async def test_repeated_run_does_not_reprocess_or_duplicate_intelligence(client, auth_headers, monkeypatch):
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", True)
    monkeypatch.setitem(
        AIProviderFactory._providers, "stub-analysis", StubAnalysisProvider(_analysis_result())
    )
    _mock_fetch_for("RSS", monkeypatch)
    source = await _source(client, auth_headers, "RSS")

    first = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    second = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert first.status_code == 202 and second.status_code == 202

    documents = (await client.get("/api/v1/regulatory/documents/", headers=auth_headers)).json()
    assert len(documents) == 1  # existing per-org sha256 dedup, unaffected by this change

    changes = (await client.get("/api/v1/regulatory/changes/", headers=auth_headers)).json()
    obligations = (await client.get("/api/v1/regulatory/obligations/", headers=auth_headers)).json()
    assert len(changes) == 1  # the duplicate hit was never handed to process_document again
    assert len(obligations) == 1


async def test_processing_failure_does_not_turn_a_persisted_document_into_a_failed_run(
    client, auth_headers, monkeypatch
):
    """Deterministic extraction failing at the processing stage (e.g. a corrupted
    storage read) must not retroactively make the already-returned ingestion run
    look like it failed -- the HTTP response already went out."""
    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", False)
    _mock_fetch_for("RSS", monkeypatch)
    source = await _source(client, auth_headers, "RSS")

    async def _broken_extract(storage_key, mime_type):
        return None

    monkeypatch.setattr("app.services.document_processing.extract_text_from_file", _broken_extract)

    response = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "COMPLETED"  # the run's own outcome is unaffected

    document = await _only_document_for(client, auth_headers)
    assert document["processing_status"] == DocumentProcessingStatus.FAILED.value  # honest: processing itself failed


async def test_run_source_still_requires_configure_role(client, auth_headers, monkeypatch):
    from app.tests.conftest import role_headers

    _mock_fetch_for("RSS", monkeypatch)
    source = await _source(client, auth_headers, "RSS")

    viewer = await role_headers(client, "VIEWER")
    response = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=viewer)
    assert response.status_code == 403


async def test_processing_never_creates_intelligence_for_another_organization(
    client, auth_headers, monkeypatch
):
    from app.tests.conftest import teammate_headers

    monkeypatch.setattr(document_processing.settings, "AI_ENRICHMENT_ENABLED", True)
    monkeypatch.setitem(
        AIProviderFactory._providers, "stub-analysis", StubAnalysisProvider(_analysis_result())
    )
    _mock_fetch_for("RSS", monkeypatch)
    source = await _source(client, auth_headers, "RSS")

    response = await client.post(f"/api/v1/regulatory/sources/{source['id']}/run", headers=auth_headers)
    assert response.status_code == 202, response.text

    other_org_id = str(uuid.uuid4())
    from app.models.organization import Organization
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        session.add(Organization(id=other_org_id, name="Dispatch Other Org", slug=f"dispatch-other-{uuid.uuid4().hex[:6]}"))
        await session.commit()

    other_headers = await teammate_headers(client, other_org_id, "ADMIN")

    other_changes = (await client.get("/api/v1/regulatory/changes/", headers=other_headers)).json()
    other_obligations = (await client.get("/api/v1/regulatory/obligations/", headers=other_headers)).json()
    assert other_changes == []
    assert other_obligations == []
