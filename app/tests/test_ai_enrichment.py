"""
AI provider failures must never damage an assessment.

    AI unavailable  ->  PARIVART still works

No test here contacts a real provider: a stub provider is registered in the factory and
made to fail in each of the ways a real one can. Every case asserts the same invariants --
the deterministic assessment survives, no fabricated narrative is stored, and the failure
is recorded under its own explicit status.
"""

import json

import httpx
import pytest
from sqlalchemy.future import select

from app.ai.base import AIProvider, AIProviderFactory
from app.db.database import AsyncSessionLocal
from app.models.impact import AIEnrichmentStatus, ImpactAssessment, ImpactItem
from app.models.intelligence import ChangeType, ObligationCategory
from app.services import ai_enrichment
from app.services.ai_enrichment import enrich_assessment
from app.tests.conftest import create_authority, create_change

PROVIDER_NAME = "stub"


class StubProvider(AIProvider):
    """Records how many times it was called and raises/returns whatever it is told to."""

    def __init__(self, raises=None, returns=None):
        self.raises = raises
        self.returns = returns
        self.calls = 0
        self.max_retries_seen = None

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def generate_structured_output(
        self, prompt, response_model, system_prompt=None, temperature=0.1, max_retries=3
    ):
        self.calls += 1
        self.max_retries_seen = max_retries
        if self.raises is not None:
            raise self.raises
        return self.returns

    async def generate_text(self, prompt, system_prompt=None, temperature=0.1) -> str:
        return ""


def _http_error(status_code: int, headers=None):
    request = httpx.Request("POST", "http://provider.invalid/generate")
    response = httpx.Response(status_code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


@pytest.fixture
def register_provider(monkeypatch):
    """Register a stub provider and switch enrichment on for the duration of a test."""

    def _register(provider: StubProvider):
        monkeypatch.setitem(AIProviderFactory._providers, PROVIDER_NAME, provider)
        monkeypatch.setattr(ai_enrichment.settings, "AI_ENRICHMENT_ENABLED", True)
        monkeypatch.setattr(ai_enrichment.settings, "AI_PROVIDER", PROVIDER_NAME)
        return provider

    return _register


async def _assessment(client, demo_org, auth_headers) -> dict:
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        change_id = await create_change(
            session,
            organization_id=demo_org.id,
            authority=authority,
            summary=(
                "Mandatory electronic labeling requirements for diagnostic and monitoring "
                "medical devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )
    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _reload(assessment_id: str):
    async with AsyncSessionLocal() as session:
        assessment = (
            await session.execute(
                select(ImpactAssessment).where(ImpactAssessment.id == assessment_id)
            )
        ).scalars().first()
        items = (
            await session.execute(
                select(ImpactItem).where(
                    ImpactItem.impact_assessment_id == assessment_id
                )
            )
        ).scalars().all()
        return assessment, list(items)


async def _assert_assessment_intact(assessment_id: str, expected_item_count: int):
    """Invariants that must hold no matter how the provider failed."""
    assessment, items = await _reload(assessment_id)
    assert assessment.status.value == "COMPLETED"
    assert assessment.overall_impact_level.value != "NO_MATCH"
    assert len(items) == expected_item_count
    # Nothing was fabricated on the AI side.
    assert assessment.ai_narrative is None
    assert assessment.ai_model is None
    assert assessment.prompt_version is None


@pytest.mark.parametrize(
    "failure, expected_status",
    [
        (_http_error(429, {"Retry-After": "120"}), AIEnrichmentStatus.RATE_LIMITED),
        (httpx.ReadTimeout("timed out"), AIEnrichmentStatus.TIMEOUT),
        (httpx.ConnectError("connection refused"), AIEnrichmentStatus.UNAVAILABLE),
        (_http_error(401), AIEnrichmentStatus.AUTH_ERROR),
        (_http_error(503), AIEnrichmentStatus.PROVIDER_ERROR),
        (json.JSONDecodeError("bad json", "{", 0), AIEnrichmentStatus.INVALID_RESPONSE),
        (RuntimeError("provider exhausted its attempts"), AIEnrichmentStatus.PROVIDER_ERROR),
    ],
)
async def test_provider_failure_records_status_and_preserves_assessment(
    client, demo_org, auth_headers, register_provider, failure, expected_status
):
    assessment = await _assessment(client, demo_org, auth_headers)
    provider = register_provider(StubProvider(raises=failure))

    status = await enrich_assessment(assessment["id"], demo_org.id)

    assert status is expected_status
    await _assert_assessment_intact(assessment["id"], len(assessment["items"]))

    stored, _ = await _reload(assessment["id"])
    assert stored.ai_enrichment_status is expected_status
    assert stored.ai_enrichment_error

    # Bounded: one attempt, no retry storm, and the provider's own loop is capped too.
    assert provider.calls == 1
    assert provider.max_retries_seen == 1


async def test_rate_limit_records_retry_after_without_waiting(
    client, demo_org, auth_headers, register_provider
):
    assessment = await _assessment(client, demo_org, auth_headers)
    provider = register_provider(
        StubProvider(raises=_http_error(429, {"Retry-After": "120"}))
    )

    status = await enrich_assessment(assessment["id"], demo_org.id)

    assert status is AIEnrichmentStatus.RATE_LIMITED
    stored, _ = await _reload(assessment["id"])
    # Retry-After is recorded for an operator, not slept on and not retried.
    assert "Retry-After=120" in stored.ai_enrichment_error
    assert provider.calls == 1


async def test_malformed_response_is_not_stored_as_success(
    client, demo_org, auth_headers, register_provider
):
    """An off-schema or empty response is INVALID_RESPONSE, never a narrative."""
    assessment = await _assessment(client, demo_org, auth_headers)
    register_provider(StubProvider(returns=ai_enrichment.ImpactNarrative(narrative="   ")))

    status = await enrich_assessment(assessment["id"], demo_org.id)

    assert status is AIEnrichmentStatus.INVALID_RESPONSE
    await _assert_assessment_intact(assessment["id"], len(assessment["items"]))


async def test_no_provider_registered_is_unavailable(
    client, demo_org, auth_headers, monkeypatch
):
    assessment = await _assessment(client, demo_org, auth_headers)
    monkeypatch.setattr(ai_enrichment.settings, "AI_ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(ai_enrichment.settings, "AI_PROVIDER", "not-registered")

    status = await enrich_assessment(assessment["id"], demo_org.id)

    assert status is AIEnrichmentStatus.UNAVAILABLE
    await _assert_assessment_intact(assessment["id"], len(assessment["items"]))


async def test_disabled_never_constructs_a_provider(client, demo_org, auth_headers):
    """With enrichment off (the default) no provider is touched at all."""
    assessment = await _assessment(client, demo_org, auth_headers)
    provider = StubProvider(raises=AssertionError("provider must not be called"))
    AIProviderFactory._providers[PROVIDER_NAME] = provider
    try:
        status = await enrich_assessment(assessment["id"], demo_org.id)
    finally:
        AIProviderFactory._providers.pop(PROVIDER_NAME, None)

    assert status is AIEnrichmentStatus.DISABLED
    assert provider.calls == 0
    await _assert_assessment_intact(assessment["id"], len(assessment["items"]))


async def test_successful_enrichment_adds_only_a_narrative(
    client, demo_org, auth_headers, register_provider
):
    assessment = await _assessment(client, demo_org, auth_headers)
    before, before_items = await _reload(assessment["id"])
    before_level = before.overall_impact_level

    register_provider(
        StubProvider(
            returns=ai_enrichment.ImpactNarrative(
                narrative="Five portfolio entities are potentially affected."
            )
        )
    )

    status = await enrich_assessment(assessment["id"], demo_org.id)
    assert status is AIEnrichmentStatus.SUCCESS

    after, after_items = await _reload(assessment["id"])
    assert after.ai_narrative == "Five portfolio entities are potentially affected."
    assert after.ai_model == f"{PROVIDER_NAME}:stub-model"
    assert after.prompt_version == ai_enrichment.PROMPT_VERSION
    # Deterministic findings are untouched by enrichment.
    assert after.overall_impact_level == before_level
    assert len(after_items) == len(before_items)


async def test_analyze_succeeds_while_provider_is_rate_limited(
    client, demo_org, auth_headers, register_provider
):
    """
    The end-to-end guarantee: enrichment is scheduled, the provider 429s, and the HTTP
    request still returns a complete deterministic assessment.
    """
    provider = register_provider(StubProvider(raises=_http_error(429)))

    assessment = await _assessment(client, demo_org, auth_headers)

    assert assessment["status"] == "COMPLETED"
    assert assessment["items"]
    assert provider.calls == 1  # background enrichment ran, and ran exactly once

    stored, items = await _reload(assessment["id"])
    assert stored.ai_enrichment_status is AIEnrichmentStatus.RATE_LIMITED
    assert stored.ai_narrative is None
    assert len(items) == len(assessment["items"])
