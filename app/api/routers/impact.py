from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api.dependencies.auth import get_current_user
from app.api.schemas.impact import (
    ImpactAssessmentCreate,
    ImpactAssessmentResponse,
    ImpactItemResponse,
)
from app.core.config import settings
from app.db.database import get_db
from app.matching.engine import MatchingEngineService
from app.models.impact import AIEnrichmentStatus, ImpactAssessment, ImpactItem
from app.models.user import User
from app.services.ai_enrichment import enrich_assessment

logger = structlog.get_logger()

router = APIRouter(prefix="/impact", tags=["Impact Assessment & Matching"])


async def _load_with_items(db: AsyncSession, assessment_id: str, organization_id: str):
    result = await db.execute(
        select(ImpactAssessment)
        .options(selectinload(ImpactAssessment.items))
        .where(
            ImpactAssessment.id == assessment_id,
            ImpactAssessment.organization_id == organization_id,
        )
    )
    return result.scalars().first()


def _schedule_enrichment(
    background_tasks: BackgroundTasks, assessment: ImpactAssessment, organization_id: str
) -> None:
    """
    Queue optional AI enrichment *after* the response is sent.

    The deterministic assessment is already committed at this point, so the request never
    waits on a provider and a provider outage cannot affect the response.
    """
    if not settings.AI_ENRICHMENT_ENABLED:
        return
    if assessment.ai_enrichment_status != AIEnrichmentStatus.DISABLED:
        return  # already attempted for this assessment
    background_tasks.add_task(enrich_assessment, assessment.id, organization_id)


@router.post(
    "/analyze",
    response_model=ImpactAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def analyze_impact(
    payload: ImpactAssessmentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run deterministic portfolio impact analysis for a regulatory change.

    The analysis makes no AI call and therefore always completes. Optional AI enrichment,
    when enabled, is scheduled in the background and never delays this response.
    """
    try:
        assessment = await MatchingEngineService.analyze_change_impact(
            db=db,
            organization_id=current_user.organization_id,
            regulatory_change_id=payload.regulatory_change_id,
            force_reanalyze=payload.force_reanalyze,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception(
            "impact_analysis_failed",
            regulatory_change_id=payload.regulatory_change_id,
            organization_id=current_user.organization_id,
        )
        raise HTTPException(status_code=500, detail="Impact analysis failed")

    _schedule_enrichment(background_tasks, assessment, current_user.organization_id)
    return await _load_with_items(db, assessment.id, current_user.organization_id)


@router.get("/", response_model=List[ImpactAssessmentResponse])
async def list_impact_assessments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    regulatory_change_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(ImpactAssessment)
        .options(selectinload(ImpactAssessment.items))
        .where(ImpactAssessment.organization_id == current_user.organization_id)
    )
    if regulatory_change_id:
        query = query.where(ImpactAssessment.regulatory_change_id == regulatory_change_id)

    result = await db.execute(
        query.order_by(ImpactAssessment.created_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()


@router.get("/{assessment_id}", response_model=ImpactAssessmentResponse)
async def get_impact_assessment(
    assessment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assessment = await _load_with_items(db, assessment_id, current_user.organization_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Impact assessment not found")
    return assessment


@router.get("/{assessment_id}/items", response_model=List[ImpactItemResponse])
async def list_assessment_items(
    assessment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owned = await db.execute(
        select(ImpactAssessment.id).where(
            ImpactAssessment.id == assessment_id,
            ImpactAssessment.organization_id == current_user.organization_id,
        )
    )
    if owned.scalars().first() is None:
        raise HTTPException(status_code=404, detail="Impact assessment not found")

    items = await db.execute(
        select(ImpactItem).where(ImpactItem.impact_assessment_id == assessment_id)
    )
    return items.scalars().all()


@router.post("/{assessment_id}/reanalyze", response_model=ImpactAssessmentResponse)
async def reanalyze_impact(
    assessment_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run the deterministic analysis, producing a new analysis_version."""
    existing = await db.execute(
        select(ImpactAssessment).where(
            ImpactAssessment.id == assessment_id,
            ImpactAssessment.organization_id == current_user.organization_id,
        )
    )
    assessment = existing.scalars().first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Impact assessment not found")

    try:
        new_assessment = await MatchingEngineService.analyze_change_impact(
            db=db,
            organization_id=current_user.organization_id,
            regulatory_change_id=assessment.regulatory_change_id,
            force_reanalyze=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("impact_reanalysis_failed", assessment_id=assessment_id)
        raise HTTPException(status_code=500, detail="Impact analysis failed")

    _schedule_enrichment(background_tasks, new_assessment, current_user.organization_id)
    return await _load_with_items(db, new_assessment.id, current_user.organization_id)
