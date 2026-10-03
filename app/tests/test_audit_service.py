"""
AuditService: recording, filtering, tenant isolation and transaction behaviour.

The last of those is the point of the class. `record()` does not commit, so these
tests assert the consequence directly: an event is visible only once the caller
commits, and a rolled-back unit of work leaves nothing behind.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.db.database import AsyncSessionLocal
from app.models.governance import AuditEvent
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.services.audit_service import (
    AUDIT_ENTITY_TYPES,
    AUDIT_EVENT_TYPES,
    ENTITY_ACTION,
    ENTITY_IMPACT_ASSESSMENT,
    EVENT_ACTION_CREATED,
    EVENT_REVIEW_FILED,
    AuditService,
)


async def _org_with_user(session, slug: str) -> tuple[str, str]:
    org = Organization(id=str(uuid.uuid4()), name=slug, slug=slug)
    session.add(org)
    await session.flush()
    user = User(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        email=f"{slug}@example.com",
        password_hash="x",
        name=f"{slug} user",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return org.id, user.id


@pytest.mark.asyncio
async def test_record_is_visible_after_the_caller_commits():
    async with AsyncSessionLocal() as session:
        org_id, user_id = await _org_with_user(session, "acme")
        AuditService.record(
            session,
            organization_id=org_id,
            actor_id=user_id,
            event_type=EVENT_REVIEW_FILED,
            entity_type=ENTITY_IMPACT_ASSESSMENT,
            entity_id="assessment-1",
            payload={"decision": "ACCEPT", "previous_state": "COMPLETED"},
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        events = await AuditService.list_events(session, organization_id=org_id)
        assert len(events) == 1
        assert events[0].event_type == EVENT_REVIEW_FILED
        assert events[0].entity_id == "assessment-1"
        assert json.loads(events[0].payload) == {
            "decision": "ACCEPT",
            "previous_state": "COMPLETED",
        }


@pytest.mark.asyncio
async def test_a_rolled_back_unit_of_work_records_nothing():
    """
    The property the whole design rests on: no event may describe a change that
    did not happen.
    """
    async with AsyncSessionLocal() as session:
        org_id, user_id = await _org_with_user(session, "rollback-co")
        await session.commit()

    async with AsyncSessionLocal() as session:
        AuditService.record(
            session,
            organization_id=org_id,
            actor_id=user_id,
            event_type=EVENT_ACTION_CREATED,
            entity_type=ENTITY_ACTION,
            entity_id="action-1",
        )
        await session.rollback()

    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(AuditEvent))
        assert total == 0


@pytest.mark.asyncio
async def test_events_are_scoped_to_one_organization():
    async with AsyncSessionLocal() as session:
        mine, my_user = await _org_with_user(session, "mine")
        theirs, their_user = await _org_with_user(session, "theirs")
        AuditService.record(
            session,
            organization_id=mine,
            actor_id=my_user,
            event_type=EVENT_ACTION_CREATED,
            entity_type=ENTITY_ACTION,
            entity_id="a",
        )
        AuditService.record(
            session,
            organization_id=theirs,
            actor_id=their_user,
            event_type=EVENT_ACTION_CREATED,
            entity_type=ENTITY_ACTION,
            entity_id="b",
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        assert [e.entity_id for e in await AuditService.list_events(
            session, organization_id=mine
        )] == ["a"]
        # And an event belonging to another tenant is not readable by id either.
        theirs_event = (
            await AuditService.list_events(session, organization_id=theirs)
        )[0]
        assert (
            await AuditService.get_event(
                session, organization_id=mine, event_id=theirs_event.id
            )
            is None
        )


@pytest.mark.asyncio
async def test_filters_narrow_by_entity_actor_type_and_time():
    async with AsyncSessionLocal() as session:
        org_id, user_id = await _org_with_user(session, "filters")
        other_user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email="second@example.com",
            password_hash="x",
            name="Second",
            role=UserRole.REVIEWER.value,
            is_active=True,
        )
        session.add(other_user)
        await session.flush()

        AuditService.record(
            session,
            organization_id=org_id,
            actor_id=user_id,
            event_type=EVENT_REVIEW_FILED,
            entity_type=ENTITY_IMPACT_ASSESSMENT,
            entity_id="assessment-1",
        )
        AuditService.record(
            session,
            organization_id=org_id,
            actor_id=other_user.id,
            event_type=EVENT_ACTION_CREATED,
            entity_type=ENTITY_ACTION,
            entity_id="action-1",
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        by_entity = await AuditService.list_events(
            session,
            organization_id=org_id,
            entity_type=ENTITY_IMPACT_ASSESSMENT,
            entity_id="assessment-1",
        )
        assert [e.event_type for e in by_entity] == [EVENT_REVIEW_FILED]

        by_actor = await AuditService.list_events(
            session, organization_id=org_id, actor_id=other_user.id
        )
        assert [e.entity_id for e in by_actor] == ["action-1"]

        by_type = await AuditService.list_events(
            session, organization_id=org_id, event_type=EVENT_ACTION_CREATED
        )
        assert len(by_type) == 1

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert (
            await AuditService.list_events(
                session, organization_id=org_id, since=future
            )
            == []
        )
        assert (
            len(await AuditService.list_events(
                session, organization_id=org_id, until=future
            ))
            == 2
        )


@pytest.mark.asyncio
async def test_the_actor_is_eager_loaded_for_the_trail():
    """The trail's purpose is 'who', so a row must carry its actor without a second query."""
    async with AsyncSessionLocal() as session:
        org_id, user_id = await _org_with_user(session, "whodunnit")
        AuditService.record(
            session,
            organization_id=org_id,
            actor_id=user_id,
            event_type=EVENT_REVIEW_FILED,
            entity_type=ENTITY_IMPACT_ASSESSMENT,
            entity_id="assessment-1",
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        event = (await AuditService.list_events(session, organization_id=org_id))[0]
        # Available after the session that loaded it has moved on, which is what
        # selectinload buys and what the response schema depends on.
    assert event.actor is not None
    assert event.actor.email == "whodunnit@example.com"


@pytest.mark.asyncio
async def test_payload_is_optional_and_omitted_rather_than_empty():
    async with AsyncSessionLocal() as session:
        org_id, user_id = await _org_with_user(session, "nopayload")
        AuditService.record(
            session,
            organization_id=org_id,
            actor_id=user_id,
            event_type=EVENT_ACTION_CREATED,
            entity_type=ENTITY_ACTION,
            entity_id="action-1",
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        assert (await AuditService.list_events(session, organization_id=org_id))[0].payload is None


def test_the_declared_vocabulary_has_no_duplicates():
    assert len(set(AUDIT_EVENT_TYPES)) == len(AUDIT_EVENT_TYPES)
    assert len(set(AUDIT_ENTITY_TYPES)) == len(AUDIT_ENTITY_TYPES)
