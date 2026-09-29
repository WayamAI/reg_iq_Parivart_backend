"""
Action service behaviour, against a real session.

The state machine and the tenant boundary are the two things worth proving here: an
action cannot be reopened once closed, and it cannot be attached to another tenant's
people or findings.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.governance import Action, ActionPriority, ActionStatus
from app.models.user import User
from app.services.action_service import ActionService, InvalidStatusTransition


async def admin_user_id(org_id: str) -> str:
    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.organization_id == org_id)
            )
        ).scalars().first()
        return user.id


async def make_action(org_id: str, **kwargs) -> str:
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=org_id,
            title=kwargs.pop("title", "Update IFU"),
            **kwargs,
        )
        return action.id


@pytest.mark.asyncio
async def test_create_action_assigns_an_id_and_defaults(demo_org):
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="Revise labelling for PulseSense",
        )
        assert uuid.UUID(action.id)
        assert action.status == ActionStatus.OPEN
        assert action.priority == ActionPriority.MEDIUM
        assert action.completed_at is None


@pytest.mark.asyncio
async def test_completing_an_action_stamps_completed_at(demo_org):
    action_id = await make_action(demo_org.id)
    async with AsyncSessionLocal() as session:
        action = await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action_id,
            new_status=ActionStatus.COMPLETED,
        )
        assert action.status == ActionStatus.COMPLETED
        assert action.completed_at is not None


@pytest.mark.asyncio
async def test_completed_actions_cannot_be_reopened(demo_org):
    action_id = await make_action(demo_org.id)
    async with AsyncSessionLocal() as session:
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action_id,
            new_status=ActionStatus.COMPLETED,
        )
    async with AsyncSessionLocal() as session:
        with pytest.raises(InvalidStatusTransition):
            await ActionService.transition_status(
                session,
                organization_id=demo_org.id,
                action_id=action_id,
                new_status=ActionStatus.IN_PROGRESS,
            )


@pytest.mark.asyncio
async def test_cancelled_actions_are_terminal(demo_org):
    action_id = await make_action(demo_org.id)
    async with AsyncSessionLocal() as session:
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action_id,
            new_status=ActionStatus.CANCELLED,
        )
    async with AsyncSessionLocal() as session:
        with pytest.raises(InvalidStatusTransition):
            await ActionService.transition_status(
                session,
                organization_id=demo_org.id,
                action_id=action_id,
                new_status=ActionStatus.OPEN,
            )


@pytest.mark.asyncio
async def test_open_to_in_progress_to_blocked_is_allowed(demo_org):
    action_id = await make_action(demo_org.id)
    for nxt in (ActionStatus.IN_PROGRESS, ActionStatus.BLOCKED, ActionStatus.COMPLETED):
        async with AsyncSessionLocal() as session:
            action = await ActionService.transition_status(
                session,
                organization_id=demo_org.id,
                action_id=action_id,
                new_status=nxt,
            )
            assert action.status == nxt


@pytest.mark.asyncio
async def test_restating_the_current_status_is_not_an_error(demo_org):
    action_id = await make_action(demo_org.id)
    async with AsyncSessionLocal() as session:
        action = await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action_id,
            new_status=ActionStatus.OPEN,
        )
        assert action.status == ActionStatus.OPEN
        assert action.completed_at is None


@pytest.mark.asyncio
async def test_status_update_through_update_action_still_checks_transitions(demo_org):
    """The partial-update path must not be a back door around the state machine."""
    action_id = await make_action(demo_org.id)
    async with AsyncSessionLocal() as session:
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action_id,
            new_status=ActionStatus.CANCELLED,
        )
    async with AsyncSessionLocal() as session:
        with pytest.raises(InvalidStatusTransition):
            await ActionService.update_action(
                session,
                organization_id=demo_org.id,
                action_id=action_id,
                status=ActionStatus.IN_PROGRESS,
            )


@pytest.mark.asyncio
async def test_owner_must_belong_to_the_organization(demo_org):
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="not found"):
            await ActionService.create_action(
                session,
                organization_id=demo_org.id,
                title="bad owner",
                owner_id=str(uuid.uuid4()),
            )


@pytest.mark.asyncio
async def test_unknown_impact_item_is_refused(demo_org):
    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError, match="not found"):
            await ActionService.create_action(
                session,
                organization_id=demo_org.id,
                title="bad item",
                impact_item_id=str(uuid.uuid4()),
            )


@pytest.mark.asyncio
async def test_actions_are_listed_only_for_their_own_organization(demo_org):
    await make_action(demo_org.id, title="Ours")
    async with AsyncSessionLocal() as session:
        ours = await ActionService.list_actions(
            session, organization_id=demo_org.id
        )
        theirs = await ActionService.list_actions(
            session, organization_id=str(uuid.uuid4())
        )
        assert [a.title for a in ours] == ["Ours"]
        assert theirs == []


@pytest.mark.asyncio
async def test_get_action_from_another_org_reads_as_missing(demo_org):
    action_id = await make_action(demo_org.id)
    async with AsyncSessionLocal() as session:
        assert (
            await ActionService.get_action(
                session, organization_id=str(uuid.uuid4()), action_id=action_id
            )
            is None
        )


@pytest.mark.asyncio
async def test_due_within_excludes_closed_work(demo_org):
    soon = datetime.now(timezone.utc) + timedelta(days=2)
    far = datetime.now(timezone.utc) + timedelta(days=90)

    due_soon = await make_action(demo_org.id, title="Due soon", due_date=soon)
    await make_action(demo_org.id, title="Due later", due_date=far)
    closed = await make_action(demo_org.id, title="Closed", due_date=soon)

    async with AsyncSessionLocal() as session:
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=closed,
            new_status=ActionStatus.COMPLETED,
        )

    async with AsyncSessionLocal() as session:
        upcoming = await ActionService.list_actions_due_within(
            session, organization_id=demo_org.id, days=7
        )
        assert [a.id for a in upcoming] == [due_soon]


@pytest.mark.asyncio
async def test_filtering_by_status_and_owner(demo_org):
    owner_id = await admin_user_id(demo_org.id)
    mine = await make_action(demo_org.id, title="Mine", owner_id=owner_id)
    await make_action(demo_org.id, title="Unassigned")

    async with AsyncSessionLocal() as session:
        assert [a.id for a in await ActionService.list_actions(
            session, organization_id=demo_org.id, owner_id=owner_id
        )] == [mine]
        assert len(await ActionService.list_actions(
            session, organization_id=demo_org.id, status=ActionStatus.OPEN
        )) == 2
        assert await ActionService.list_actions(
            session, organization_id=demo_org.id, status=ActionStatus.COMPLETED
        ) == []
