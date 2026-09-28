"""
Optional AI enrichment for an Impact Assessment.

Contract:

    deterministic assessment  ->  always available
    optional AI enrichment    ->  only when available

Enrichment never runs inside the critical request path, never retries in a loop, never
sleeps waiting for a provider, and never alters the deterministic impact items or the
overall impact level. Any provider problem is recorded as an explicit
`AIEnrichmentStatus`; a failure is never written back as a success.
"""

import json
from typing import Optional, Tuple

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.ai.base import AIProviderFactory
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.models.impact import AIEnrichmentStatus, ImpactAssessment

logger = structlog.get_logger()

PROMPT_VERSION = "impact-narrative-v1"


class ImpactNarrative(BaseModel):
    """The only thing enrichment is allowed to contribute: prose, no new findings."""

    narrative: str


def classify_provider_error(exc: BaseException) -> Tuple[AIEnrichmentStatus, str]:
    """Map a provider exception onto an explicit status. Never raises."""
    if isinstance(exc, httpx.TimeoutException):
        return AIEnrichmentStatus.TIMEOUT, f"provider timed out: {exc}"

    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            retry_after = exc.response.headers.get("Retry-After")
            detail = "provider rate limited (429)"
            if retry_after:
                # Recorded for the operator, not acted on: we do not sleep and retry.
                detail += f"; Retry-After={retry_after}"
            return AIEnrichmentStatus.RATE_LIMITED, detail
        if code in (401, 403):
            return AIEnrichmentStatus.AUTH_ERROR, f"provider rejected credentials ({code})"
        return AIEnrichmentStatus.PROVIDER_ERROR, f"provider returned HTTP {code}"

    if isinstance(exc, httpx.RequestError):
        return AIEnrichmentStatus.UNAVAILABLE, f"provider unreachable: {exc}"

    if isinstance(exc, (ValidationError, json.JSONDecodeError, ValueError)):
        return AIEnrichmentStatus.INVALID_RESPONSE, f"unusable provider response: {exc}"

    # RuntimeError is what the bundled providers raise once their own attempts are spent.
    return AIEnrichmentStatus.PROVIDER_ERROR, f"{type(exc).__name__}: {exc}"


def _build_prompt(assessment: ImpactAssessment) -> str:
    lines = [
        "Summarise the following regulatory impact assessment for a compliance reviewer.",
        "Use only the findings given. Do not add products, markets, obligations or",
        "impacts that are not listed. If something is not stated, say it is unassessed.",
        "",
        f"Overall impact level: {assessment.overall_impact_level}",
        f"Deterministic summary: {assessment.summary}",
        "",
        "Affected entities:",
    ]
    for item in assessment.items:
        lines.append(
            f"- {item.entity_type} {item.entity_id}: {item.impact_level} "
            f"(match_types={item.match_types}) -- {item.reason}"
        )
    return "\n".join(lines)


async def enrich_assessment(
    assessment_id: str,
    organization_id: str,
    db: Optional[AsyncSession] = None,
) -> AIEnrichmentStatus:
    """
    Attempt to attach an AI narrative to an already-persisted assessment.

    Returns the recorded status. Never raises: the deterministic assessment is already
    committed and must not be endangered by anything that happens here.
    """
    if db is not None:
        return await _enrich(db, assessment_id, organization_id)
    async with AsyncSessionLocal() as session:
        return await _enrich(session, assessment_id, organization_id)


async def _enrich(
    db: AsyncSession, assessment_id: str, organization_id: str
) -> AIEnrichmentStatus:
    result = await db.execute(
        select(ImpactAssessment)
        .options(selectinload(ImpactAssessment.items))
        .where(
            ImpactAssessment.id == assessment_id,
            ImpactAssessment.organization_id == organization_id,
        )
    )
    assessment = result.scalars().first()
    if assessment is None:
        logger.warning("ai_enrichment_assessment_missing", assessment_id=assessment_id)
        return AIEnrichmentStatus.UNAVAILABLE

    if not settings.AI_ENRICHMENT_ENABLED:
        return await _record(db, assessment, AIEnrichmentStatus.DISABLED, None, None)

    try:
        provider = AIProviderFactory.get_provider(settings.AI_PROVIDER)
    except Exception as exc:
        # No provider is registered in this deployment. That is a configuration state,
        # not an assessment failure.
        return await _record(
            db, assessment, AIEnrichmentStatus.UNAVAILABLE, f"no provider available: {exc}", None
        )

    try:
        narrative = await provider.generate_structured_output(
            prompt=_build_prompt(assessment),
            response_model=ImpactNarrative,
            system_prompt=(
                "You are a regulatory compliance analyst. Summarise only the findings you "
                "are given. Never invent business impact."
            ),
            temperature=0.1,
            max_retries=max(1, settings.AI_MAX_ATTEMPTS),
        )
    except BaseException as exc:  # noqa: BLE001 - deliberately total
        status, detail = classify_provider_error(exc)
        logger.warning(
            "ai_enrichment_failed",
            assessment_id=assessment_id,
            ai_enrichment_status=status.value,
            detail=detail,
        )
        return await _record(db, assessment, status, detail, None)

    text = getattr(narrative, "narrative", None)
    if not text or not str(text).strip():
        return await _record(
            db, assessment, AIEnrichmentStatus.INVALID_RESPONSE, "provider returned an empty narrative", None
        )

    return await _record(db, assessment, AIEnrichmentStatus.SUCCESS, None, str(text), provider=provider)


async def _record(
    db: AsyncSession,
    assessment: ImpactAssessment,
    status: AIEnrichmentStatus,
    error: Optional[str],
    narrative: Optional[str],
    provider=None,
) -> AIEnrichmentStatus:
    """
    Persist the enrichment outcome.

    Deterministic fields (status, overall_impact_level, overall_confidence, items) are
    untouched. On anything other than SUCCESS, narrative and ai_model stay NULL so no
    consumer can mistake a failure for an AI result.
    """
    assessment.ai_enrichment_status = status
    assessment.ai_enrichment_error = error
    if status is AIEnrichmentStatus.SUCCESS:
        assessment.ai_narrative = narrative
        assessment.prompt_version = PROMPT_VERSION
        if provider is not None:
            assessment.ai_model = f"{provider.provider_name}:{provider.model_name}"
    else:
        assessment.ai_narrative = None
        assessment.ai_model = None
        assessment.prompt_version = None
    await db.commit()
    return status
