"""
Human review of an Impact Assessment (Phase 7).

A review is the point where a person accepts, modifies, rejects or defers what the
deterministic engine produced. Two properties matter more than anything else here:

  * Every query is scoped to an organization. A review is read back only by the tenant
    that owns the assessment it belongs to -- never via the URL alone.
  * Reviews are append-only. Filing a decision inserts a row and moves the assessment's
    status; it never rewrites an earlier decision. `previous_state` and `new_state` on
    each row make the whole trail reconstructable.
"""

import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import ImpactReview, ReviewDecision
from app.models.impact import ImpactAssessment, ImpactAssessmentStatus
from app.models.user import User

# An assessment can only be reviewed once the engine has produced something to review.
# PENDING and ANALYZING have no result yet; FAILED has no result at all.
REVIEWABLE_STATUSES: frozenset[ImpactAssessmentStatus] = frozenset(
    {
        ImpactAssessmentStatus.COMPLETED,
        ImpactAssessmentStatus.REQUIRES_REVIEW,
        ImpactAssessmentStatus.REVIEWED,
    }
)

# Where each decision leaves the assessment. ACCEPT and MODIFY close the loop; REJECT and
# NEEDS_MORE_INFORMATION send it back for another pass.
DECISION_OUTCOMES: dict[ReviewDecision, ImpactAssessmentStatus] = {
    ReviewDecision.ACCEPT: ImpactAssessmentStatus.REVIEWED,
    ReviewDecision.MODIFY: ImpactAssessmentStatus.REVIEWED,
    ReviewDecision.REJECT: ImpactAssessmentStatus.REQUIRES_REVIEW,
    ReviewDecision.NEEDS_MORE_INFORMATION: ImpactAssessmentStatus.REQUIRES_REVIEW,
}


class ReviewNotAllowed(Exception):
    """A review was filed against an assessment that is not in a reviewable state."""


class ReviewService:
    """Organization-scoped operations over ImpactReview."""

    @staticmethod
    async def create_review(
        session: AsyncSession,
        *,
        organization_id: str,
        impact_assessment_id: str,
        reviewer_id: str,
        decision: ReviewDecision,
        notes: Optional[str] = None,
    ) -> ImpactReview:
        """
        File a review decision and move the assessment to its resulting state.

        Raises ValueError when the assessment or reviewer is not visible to this
        organization, and ReviewNotAllowed when the assessment cannot be reviewed yet.
        """
        assessment = (
            await session.execute(
                select(ImpactAssessment).where(
                    ImpactAssessment.id == impact_assessment_id,
                    ImpactAssessment.organization_id == organization_id,
                )
            )
        ).scalars().first()
        if assessment is None:
            raise ValueError(f"Impact assessment {impact_assessment_id} not found")

        reviewer = (
            await session.execute(
                select(User).where(
                    User.id == reviewer_id,
                    User.organization_id == organization_id,
                )
            )
        ).scalars().first()
        if reviewer is None:
            raise ValueError(f"User {reviewer_id} not found")

        if assessment.status not in REVIEWABLE_STATUSES:
            raise ReviewNotAllowed(
                f"Impact assessment {impact_assessment_id} is {assessment.status.value} "
                f"and cannot be reviewed yet"
            )

        previous_state = assessment.status.value
        new_status = DECISION_OUTCOMES[decision]

        review = ImpactReview(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            impact_assessment_id=impact_assessment_id,
            reviewer_id=reviewer_id,
            decision=decision,
            notes=notes,
            previous_state=previous_state,
            new_state=new_status.value,
        )
        session.add(review)
        # The status move and the review row are one unit of work: an assessment must
        # never end up in a reviewed state with no review explaining why.
        assessment.status = new_status

        await session.commit()
        await session.refresh(review)
        return review

    @staticmethod
    async def get_review(
        session: AsyncSession, *, organization_id: str, review_id: str
    ) -> Optional[ImpactReview]:
        return (
            await session.execute(
                select(ImpactReview).where(
                    ImpactReview.id == review_id,
                    ImpactReview.organization_id == organization_id,
                )
            )
        ).scalars().first()

    @staticmethod
    async def list_reviews(
        session: AsyncSession,
        *,
        organization_id: str,
        impact_assessment_id: Optional[str] = None,
        reviewer_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ImpactReview]:
        """
        Reviews owned by this organization, newest first.

        With no filter this returns the organization's whole review trail rather than an
        empty list -- the tenant boundary is what keeps the query bounded, not the caller
        remembering to pass a filter.
        """
        query = select(ImpactReview).where(
            ImpactReview.organization_id == organization_id
        )
        if impact_assessment_id is not None:
            query = query.where(
                ImpactReview.impact_assessment_id == impact_assessment_id
            )
        if reviewer_id is not None:
            query = query.where(ImpactReview.reviewer_id == reviewer_id)

        result = await session.execute(
            query.order_by(ImpactReview.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())
