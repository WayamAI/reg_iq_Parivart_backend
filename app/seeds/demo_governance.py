"""
Demo governance data: an action with evidence, and a real audit trail behind it.

Phase 8 shipped Evidence and the audit trail, but the seed never exercised either, so a
freshly seeded database showed both features as empty lists. This fills them.

Nothing here writes an Evidence or AuditEvent row directly. Every record is produced by
driving the real services -- ActionService, ReviewService, EvidenceService -- so the audit
events carry genuine actor, entity, timestamp and previous -> new state values rather than
plausible-looking ones, and the evidence files genuinely exist in storage and really
download.

Additive and idempotent, like the rest of the seed: it is keyed on the demo action's title
and skips every block whose record already exists. It never drops, overwrites or
transitions anything that was already there.
"""

import io
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import (
    Action,
    ActionPriority,
    ActionStatus,
    Evidence,
    ImpactReview,
    ReviewDecision,
)
from app.models.impact import ImpactAssessment, ImpactItem
from app.models.organization import Organization
from app.models.user import User
from app.seeds.demo_data import DEMO_ORG_SLUG
from app.services.action_service import ActionService
from app.services.evidence_service import EvidenceService
from app.services.review_service import REVIEWABLE_STATUSES, ReviewService

# The seed's own action. Also the idempotency key: this title existing in the demo
# organization means this module has already run.
DEMO_ACTION_TITLE = "Demo: assemble the labelling evidence pack"

DEMO_EVIDENCE = [
    (
        "qa-signoff.txt",
        "QA sign-off for the revised labelling artwork.",
        "PARIVART demo evidence -- QA sign-off\n"
        "Revised labelling artwork reviewed against the updated requirement.\n"
        "Outcome: approved. Reviewer: Quality Assurance.\n",
    ),
    (
        "labelling-change-record.txt",
        "Change record for the labelling update.",
        "PARIVART demo evidence -- labelling change record\n"
        "Change: symbol set and UDI placement updated on the carton.\n"
        "Affected processes: Labeling, Packaging, Regulatory Submission.\n",
    ),
]


async def _demo_org(db: AsyncSession) -> Optional[Organization]:
    return (
        await db.execute(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
    ).scalars().first()


async def _actor(db: AsyncSession, org_id: str) -> Optional[User]:
    """An admin to attribute the seeded work to, so the trail has a real WHO."""
    return (
        await db.execute(
            select(User)
            .where(User.organization_id == org_id)
            .order_by(User.created_at.asc(), User.email.asc())
            .limit(1)
        )
    ).scalars().first()


async def _unreviewed_assessment(db: AsyncSession, org_id: str) -> Optional[ImpactAssessment]:
    """A reviewable assessment carrying no review yet, or None."""
    reviewed = select(ImpactReview.impact_assessment_id).where(
        ImpactReview.organization_id == org_id
    )
    return (
        await db.execute(
            select(ImpactAssessment)
            .where(
                ImpactAssessment.organization_id == org_id,
                ImpactAssessment.status.in_(REVIEWABLE_STATUSES),
                ImpactAssessment.id.notin_(reviewed),
            )
            .order_by(ImpactAssessment.created_at.asc())
            .limit(1)
        )
    ).scalars().first()


async def seed_demo_governance(db: AsyncSession) -> dict:
    """
    Add a reviewed assessment, a demo action and its evidence.

    Returns a summary of what was created so a caller can report it honestly. Every value
    is 0 on a second run.
    """
    created = {"reviews": 0, "actions": 0, "transitions": 0, "evidence": 0}

    org = await _demo_org(db)
    if org is None:
        print("Demo governance: organization not seeded yet, skipped.")
        return created
    org_id = org.id

    actor = await _actor(db, org_id)
    actor_id = actor.id if actor else None

    # 1. A human review, so the audit trail carries a REVIEW_FILED event with the
    #    assessment's previous and new state.
    assessment = await _unreviewed_assessment(db, org_id)
    if assessment is not None and actor_id is not None:
        await ReviewService.create_review(
            db,
            organization_id=org_id,
            impact_assessment_id=assessment.id,
            reviewer_id=actor_id,
            decision=ReviewDecision.ACCEPT,
            notes="Demo review: findings accepted, remediation raised as an action.",
        )
        created["reviews"] += 1

    # 2. The demo action. Existing actions are left exactly as they are -- this module
    #    raises its own rather than transitioning work someone else recorded.
    existing = (
        await db.execute(
            select(Action).where(
                Action.organization_id == org_id, Action.title == DEMO_ACTION_TITLE
            )
        )
    ).scalars().first()

    if existing is None:
        item = (
            await db.execute(
                select(ImpactItem)
                .join(ImpactAssessment, ImpactItem.impact_assessment_id == ImpactAssessment.id)
                .where(ImpactAssessment.organization_id == org_id)
                .order_by(ImpactItem.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

        action = await ActionService.create_action(
            db,
            organization_id=org_id,
            title=DEMO_ACTION_TITLE,
            description=(
                "Collect the QA sign-off and change record substantiating the labelling "
                "update, and file them as evidence against this action."
            ),
            owner_id=actor_id,
            impact_item_id=item.id if item else None,
            priority=ActionPriority.HIGH,
            due_date=datetime.now(timezone.utc) + timedelta(days=21),
            actor_id=actor_id,
        )
        created["actions"] += 1

        # A real transition through the state machine, so the trail shows OPEN -> IN_PROGRESS
        # rather than an action that was simply born in progress.
        await ActionService.transition_status(
            db,
            organization_id=org_id,
            action_id=action.id,
            new_status=ActionStatus.IN_PROGRESS,
            actor_id=actor_id,
        )
        created["transitions"] += 1
    else:
        action = existing

    # 3. Evidence, filed through the service so the bytes land in storage and
    #    GET /evidence/{id}/download really streams them.
    already = (
        await db.execute(
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.action_id == action.id)
        )
    ).scalar() or 0

    if already == 0:
        for filename, description, body in DEMO_EVIDENCE:
            await EvidenceService.attach(
                db,
                organization_id=org_id,
                action_id=action.id,
                file_data=io.BytesIO(body.encode("utf-8")),
                file_name=filename,
                content_type="text/plain",
                description=description,
                actor_id=actor_id,
            )
            created["evidence"] += 1

    print(f"Demo governance: {created}")
    return created
