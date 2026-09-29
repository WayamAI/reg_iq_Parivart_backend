"""
Review service behaviour, against a real session and real assessments.

These cover the three things that make a review trustworthy: it only attaches to an
assessment the tenant owns, it only lands on an assessment that is ready to be reviewed,
and it records where the assessment went as well as where it came from.
"""

import uuid

import pytest
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.governance import ReviewDecision
from app.models.impact import ImpactAssessment, ImpactAssessmentStatus
from app.models.intelligence import ChangeType, ObligationCategory
from app.models.user import User
from app.services.review_service import (
    DECISION_OUTCOMES,
    REVIEWABLE_STATUSES,
    ReviewNotAllowed,
    ReviewService,
)
from app.tests.conftest import create_authority, create_change


async def make_assessment(client, headers, org_id) -> str:
    """Run a real deterministic analysis and return the assessment id."""
    async with AsyncSessionLocal() as session:
        authority = await create_authority(
            session, short_name="FDA", jurisdiction="United States", country="USA"
        )
        change_id = await create_change(
            session,
            organization_id=org_id,
            authority=authority,
            summary=(
                "Mandatory electronic labeling requirements for monitoring medical "
                "devices in the US market."
            ),
            change_type=ChangeType.LABELING_CHANGE,
            obligation_category=ObligationCategory.LABELING,
        )
    res = await client.post(
        "/api/v1/impact/analyze",
        json={"regulatory_change_id": change_id, "force_reanalyze": True},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def admin_user_id(org_id: str) -> str:
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.organization_id == org_id)
            )
        ).scalars().first()
        return user.id


def test_decision_outcomes_cover_every_decision():
    assert set(DECISION_OUTCOMES) == set(ReviewDecision)


def test_unfinished_assessments_are_not_reviewable():
    """An assessment with no result yet, or none at all, cannot be reviewed."""
    assert ImpactAssessmentStatus.PENDING not in REVIEWABLE_STATUSES
    assert ImpactAssessmentStatus.ANALYZING not in REVIEWABLE_STATUSES
    assert ImpactAssessmentStatus.FAILED not in REVIEWABLE_STATUSES


@pytest.mark.asyncio
async def test_accept_records_both_states_and_moves_the_assessment(
    client, demo_org, auth_headers
):
    assessment_id = await make_assessment(client, auth_headers, demo_org.id)
    reviewer_id = await admin_user_id(demo_org.id)

    async with AsyncSessionLocal() as session:
        review = await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=assessment_id,
            reviewer_id=reviewer_id,
            decision=ReviewDecision.ACCEPT,
            notes="Matches our US labelling exposure.",
        )
        assert review.id
        assert review.organization_id == demo_org.id
        assert review.previous_state == "COMPLETED"
        assert review.new_state == "REVIEWED"

    async with AsyncSessionLocal() as session:
        assessment = await session.get(ImpactAssessment, assessment_id)
        assert assessment.status == ImpactAssessmentStatus.REVIEWED


@pytest.mark.asyncio
async def test_reject_sends_the_assessment_back_for_another_pass(
    client, demo_org, auth_headers
):
    assessment_id = await make_assessment(client, auth_headers, demo_org.id)
    reviewer_id = await admin_user_id(demo_org.id)

    async with AsyncSessionLocal() as session:
        review = await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=assessment_id,
            reviewer_id=reviewer_id,
            decision=ReviewDecision.REJECT,
            notes="Wrong product family.",
        )
        assert review.new_state == "REQUIRES_REVIEW"

    async with AsyncSessionLocal() as session:
        assessment = await session.get(ImpactAssessment, assessment_id)
        assert assessment.status == ImpactAssessmentStatus.REQUIRES_REVIEW


@pytest.mark.asyncio
async def test_reviews_are_append_only(client, demo_org, auth_headers):
    """A second decision adds a row; the first decision stays exactly as it was."""
    assessment_id = await make_assessment(client, auth_headers, demo_org.id)
    reviewer_id = await admin_user_id(demo_org.id)

    async with AsyncSessionLocal() as session:
        first = await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=assessment_id,
            reviewer_id=reviewer_id,
            decision=ReviewDecision.NEEDS_MORE_INFORMATION,
            notes="Need the notified body's position first.",
        )
        first_id, first_decision = first.id, first.decision

    async with AsyncSessionLocal() as session:
        second = await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=assessment_id,
            reviewer_id=reviewer_id,
            decision=ReviewDecision.ACCEPT,
            notes="Position received, accepting.",
        )
        assert second.id != first_id
        # The second review starts from where the first one left the assessment.
        assert second.previous_state == "REQUIRES_REVIEW"
        assert second.new_state == "REVIEWED"

    async with AsyncSessionLocal() as session:
        trail = await ReviewService.list_reviews(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=assessment_id,
        )
        assert len(trail) == 2
        preserved = next(r for r in trail if r.id == first_id)
        assert preserved.decision == first_decision
        assert preserved.notes == "Need the notified body's position first."


@pytest.mark.asyncio
async def test_review_on_an_unfinished_assessment_is_refused(
    client, demo_org, auth_headers
):
    assessment_id = await make_assessment(client, auth_headers, demo_org.id)
    reviewer_id = await admin_user_id(demo_org.id)

    async with AsyncSessionLocal() as session:
        assessment = await session.get(ImpactAssessment, assessment_id)
        assessment.status = ImpactAssessmentStatus.ANALYZING
        await session.commit()

    async with AsyncSessionLocal() as session:
        with pytest.raises(ReviewNotAllowed):
            await ReviewService.create_review(
                session,
                organization_id=demo_org.id,
                impact_assessment_id=assessment_id,
                reviewer_id=reviewer_id,
                decision=ReviewDecision.ACCEPT,
            )


@pytest.mark.asyncio
async def test_review_against_an_unknown_assessment_is_refused(demo_org):
    reviewer_id = await admin_user_id(demo_org.id)
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="not found"):
            await ReviewService.create_review(
                session,
                organization_id=demo_org.id,
                impact_assessment_id=str(uuid.uuid4()),
                reviewer_id=reviewer_id,
                decision=ReviewDecision.ACCEPT,
            )


@pytest.mark.asyncio
async def test_listing_with_no_filter_returns_the_orgs_trail(
    client, demo_org, auth_headers
):
    """No filter means the tenant's whole trail, not an empty list."""
    assessment_id = await make_assessment(client, auth_headers, demo_org.id)
    reviewer_id = await admin_user_id(demo_org.id)

    async with AsyncSessionLocal() as session:
        await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=assessment_id,
            reviewer_id=reviewer_id,
            decision=ReviewDecision.ACCEPT,
        )

    async with AsyncSessionLocal() as session:
        assert len(await ReviewService.list_reviews(
            session, organization_id=demo_org.id
        )) == 1
