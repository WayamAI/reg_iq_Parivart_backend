"""
Phase 7 governance model tests.

These exercise the real tables through a real session. The point is to catch what a
`hasattr` assertion cannot: a primary key that is never populated, a NOT NULL column with
no value, and a foreign key that does not resolve.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.database import AsyncSessionLocal
from app.models.governance import (
    ACTION_TRANSITIONS,
    TERMINAL_ACTION_STATUSES,
    Action,
    ActionPriority,
    ActionStatus,
    ImpactReview,
    ReviewDecision,
)
from app.models.user import User


def test_action_status_enum_values():
    assert {s.value for s in ActionStatus} == {
        "OPEN",
        "IN_PROGRESS",
        "BLOCKED",
        "COMPLETED",
        "CANCELLED",
    }


def test_review_decision_enum_values():
    assert {d.value for d in ReviewDecision} == {
        "ACCEPT",
        "MODIFY",
        "REJECT",
        "NEEDS_MORE_INFORMATION",
    }


def test_completed_and_cancelled_are_terminal():
    assert ACTION_TRANSITIONS[ActionStatus.COMPLETED] == frozenset()
    assert ACTION_TRANSITIONS[ActionStatus.CANCELLED] == frozenset()
    assert TERMINAL_ACTION_STATUSES == {ActionStatus.COMPLETED, ActionStatus.CANCELLED}


def test_every_status_has_a_transition_entry():
    assert set(ACTION_TRANSITIONS) == set(ActionStatus)


@pytest.mark.asyncio
async def test_action_persists_with_defaults(demo_org):
    """A minimally-specified action round-trips with OPEN/MEDIUM defaults applied."""
    async with AsyncSessionLocal() as session:
        action = Action(
            id=str(uuid.uuid4()),
            organization_id=demo_org.id,
            title="Update IFU for EU MDR labelling change",
        )
        session.add(action)
        await session.commit()
        await session.refresh(action)

        assert action.status == ActionStatus.OPEN
        assert action.priority == ActionPriority.MEDIUM
        assert action.completed_at is None
        assert action.created_at is not None


@pytest.mark.asyncio
async def test_action_requires_an_organization(demo_org):
    """organization_id is NOT NULL: an untenanted action must not reach the table."""
    async with AsyncSessionLocal() as session:
        session.add(Action(id=str(uuid.uuid4()), title="orphan"))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_action_owner_foreign_key_is_enforced(demo_org):
    async with AsyncSessionLocal() as session:
        session.add(
            Action(
                id=str(uuid.uuid4()),
                organization_id=demo_org.id,
                title="bad owner",
                owner_id="does-not-exist",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_action_due_date_and_priority_round_trip(demo_org):
    due = datetime.now(timezone.utc) + timedelta(days=30)
    async with AsyncSessionLocal() as session:
        action = Action(
            id=str(uuid.uuid4()),
            organization_id=demo_org.id,
            title="Submit updated technical file",
            priority=ActionPriority.HIGH,
            due_date=due,
        )
        session.add(action)
        await session.commit()

        loaded = (
            await session.execute(select(Action).where(Action.id == action.id))
        ).scalars().one()
        assert loaded.priority == ActionPriority.HIGH
        assert loaded.due_date is not None


@pytest.mark.asyncio
async def test_review_requires_a_decision(demo_org):
    """decision is NOT NULL -- a review with no decision is not a review."""
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.organization_id == demo_org.id)
            )
        ).scalars().first()
        session.add(
            ImpactReview(
                id=str(uuid.uuid4()),
                organization_id=demo_org.id,
                impact_assessment_id=str(uuid.uuid4()),
                reviewer_id=user.id,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_review_requires_an_organization(demo_org):
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.organization_id == demo_org.id)
            )
        ).scalars().first()
        session.add(
            ImpactReview(
                id=str(uuid.uuid4()),
                impact_assessment_id=str(uuid.uuid4()),
                reviewer_id=user.id,
                decision=ReviewDecision.ACCEPT,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
