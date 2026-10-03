"""
The governance seed fills Evidence and the audit trail, and does it only once.

The point of the module is that nothing is hand-inserted: the audit events must come from
the real services, which is what makes their previous -> new state values real.
"""

import pytest
from sqlalchemy import func, select

from app.db.database import AsyncSessionLocal
from app.models.governance import Action, ActionStatus, AuditEvent, Evidence, ImpactReview
from app.seeds.demo_governance import DEMO_ACTION_TITLE, seed_demo_governance
from app.services.audit_service import (
    EVENT_ACTION_CREATED,
    EVENT_ACTION_STATUS_CHANGED,
    EVENT_EVIDENCE_ATTACHED,
    EVENT_REVIEW_FILED,
)


async def _count(model, *where):
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(func.count()).select_from(model).where(*where))
        ).scalar()


async def _event_types(org_id):
    async with AsyncSessionLocal() as session:
        return set(
            (
                await session.execute(
                    select(AuditEvent.event_type).where(
                        AuditEvent.organization_id == org_id
                    )
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_seed_creates_review_action_transition_and_evidence(
    demo_org, seeded_assessment
):
    async with AsyncSessionLocal() as session:
        created = await seed_demo_governance(session)

    assert created == {"reviews": 1, "actions": 1, "transitions": 1, "evidence": 2}
    assert await _count(Evidence, Evidence.organization_id == demo_org.id) == 2
    assert await _count(ImpactReview, ImpactReview.organization_id == demo_org.id) >= 1

    assert {
        EVENT_REVIEW_FILED,
        EVENT_ACTION_CREATED,
        EVENT_ACTION_STATUS_CHANGED,
        EVENT_EVIDENCE_ATTACHED,
    } <= await _event_types(demo_org.id)


@pytest.mark.asyncio
async def test_seeded_action_went_through_the_state_machine(demo_org, seeded_assessment):
    async with AsyncSessionLocal() as session:
        await seed_demo_governance(session)

    async with AsyncSessionLocal() as session:
        action = (
            await session.execute(
                select(Action).where(Action.title == DEMO_ACTION_TITLE)
            )
        ).scalars().first()

    assert action is not None
    assert action.status is ActionStatus.IN_PROGRESS

    async with AsyncSessionLocal() as session:
        event = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.event_type == EVENT_ACTION_STATUS_CHANGED,
                    AuditEvent.entity_id == action.id,
                )
            )
        ).scalars().first()

    # Real previous -> new state, because the transition went through ActionService.
    assert event is not None
    assert event.actor_id is not None
    assert '"from": "OPEN"' in event.payload
    assert '"to": "IN_PROGRESS"' in event.payload


@pytest.mark.asyncio
async def test_seed_is_idempotent(demo_org, seeded_assessment):
    async with AsyncSessionLocal() as session:
        await seed_demo_governance(session)
    async with AsyncSessionLocal() as session:
        second = await seed_demo_governance(session)

    assert second == {"reviews": 0, "actions": 0, "transitions": 0, "evidence": 0}
    assert await _count(Evidence, Evidence.organization_id == demo_org.id) == 2
    assert await _count(Action, Action.title == DEMO_ACTION_TITLE) == 1


@pytest.mark.asyncio
async def test_seed_no_ops_without_a_demo_organization():
    """A database with no demo org is skipped, not crashed."""
    async with AsyncSessionLocal() as session:
        created = await seed_demo_governance(session)

    assert created == {"reviews": 0, "actions": 0, "transitions": 0, "evidence": 0}


@pytest.mark.asyncio
async def test_seeded_evidence_really_downloads(client, demo_org, auth_headers, seeded_assessment):
    async with AsyncSessionLocal() as session:
        await seed_demo_governance(session)

    listing = await client.get("/api/v1/evidence/", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 2

    download = await client.get(
        f"/api/v1/evidence/{rows[0]['id']}/download", headers=auth_headers
    )
    assert download.status_code == 200
    assert b"PARIVART demo evidence" in download.content
