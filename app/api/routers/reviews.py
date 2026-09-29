from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.schemas.review import ReviewCreate, ReviewResponse
from app.db.database import get_db
from app.models.user import User
from app.services.review_service import ReviewNotAllowed, ReviewService

logger = structlog.get_logger()

router = APIRouter(prefix="/reviews", tags=["Human Review"])


@router.post("/", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    File a review decision against an impact assessment.

    The reviewer is the authenticated user and the tenant is their organization; neither
    is taken from the request. An assessment belonging to another tenant is reported as
    missing, exactly like one that does not exist.
    """
    try:
        review = await ReviewService.create_review(
            db,
            organization_id=current_user.organization_id,
            impact_assessment_id=payload.impact_assessment_id,
            reviewer_id=current_user.id,
            decision=payload.decision,
            notes=payload.notes,
        )
    except ReviewNotAllowed as exc:
        # The assessment exists and is visible, but is not in a state that can carry a
        # decision yet. That is a conflict with current state, not a bad request.
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return review


@router.get("/", response_model=List[ReviewResponse])
async def list_reviews(
    impact_assessment_id: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The organization's review trail, newest first."""
    return await ReviewService.list_reviews(
        db,
        organization_id=current_user.organization_id,
        impact_assessment_id=impact_assessment_id,
        reviewer_id=reviewer_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = await ReviewService.get_review(
        db, organization_id=current_user.organization_id, review_id=review_id
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review
