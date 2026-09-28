import json
from typing import List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.dependencies.auth import get_current_user
from app.api.schemas.impact import ImpactReportCreate, ImpactReportResponse
from app.db.database import get_db
from app.models.impact import ImpactReport
from app.models.user import User
from app.services.report_service import ReportService

logger = structlog.get_logger()

router = APIRouter(prefix="/reports", tags=["Impact Delta Reports"])


def _to_response(report: ImpactReport) -> ImpactReportResponse:
    return ImpactReportResponse(
        id=report.id,
        organization_id=report.organization_id,
        impact_assessment_id=report.impact_assessment_id,
        regulatory_change_id=report.regulatory_change_id,
        title=report.title,
        summary=report.summary,
        status=report.status,
        version=report.version,
        report_data=(
            json.loads(report.report_data)
            if isinstance(report.report_data, str)
            else report.report_data
        ),
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.post(
    "/generate", response_model=ImpactReportResponse, status_code=status.HTTP_201_CREATED
)
async def generate_report(
    payload: ImpactReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate an Impact Delta Report from a persisted deterministic assessment."""
    try:
        report = await ReportService.generate_delta_report(
            db=db,
            organization_id=current_user.organization_id,
            impact_assessment_id=payload.impact_assessment_id,
            title=payload.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception(
            "report_generation_failed",
            impact_assessment_id=payload.impact_assessment_id,
            organization_id=current_user.organization_id,
        )
        raise HTTPException(status_code=500, detail="Report generation failed")

    return _to_response(report)


@router.get("/", response_model=List[ImpactReportResponse])
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ImpactReport)
        .where(ImpactReport.organization_id == current_user.organization_id)
        .order_by(ImpactReport.created_at.desc(), ImpactReport.version.desc())
        .offset(skip)
        .limit(limit)
    )
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{report_id}", response_model=ImpactReportResponse)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ImpactReport).where(
            ImpactReport.id == report_id,
            ImpactReport.organization_id == current_user.organization_id,
        )
    )
    report = result.scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="Impact report not found")
    return _to_response(report)


@router.get("/{report_id}/versions", response_model=List[ImpactReportResponse])
async def list_report_versions(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All report versions generated for the same assessment as the given report."""
    target = await db.execute(
        select(ImpactReport).where(
            ImpactReport.id == report_id,
            ImpactReport.organization_id == current_user.organization_id,
        )
    )
    report = target.scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="Impact report not found")

    versions = await db.execute(
        select(ImpactReport)
        .where(
            ImpactReport.organization_id == current_user.organization_id,
            ImpactReport.impact_assessment_id == report.impact_assessment_id,
        )
        .order_by(ImpactReport.version.desc())
    )
    return [_to_response(r) for r in versions.scalars().all()]
