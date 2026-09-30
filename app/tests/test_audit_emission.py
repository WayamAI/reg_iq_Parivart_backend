"""
What the governance services actually write to the trail.

These tests exist to pin two things that are easy to regress and expensive to get
wrong: that a real change is recorded with the right before/after states, and that
a *refused* change records nothing at all. The second is the harder guarantee and
the reason `AuditService.record()` never commits on its own.
"""

import json

import pytest
from sqlalchemy import func, select

from app.db.database import AsyncSessionLocal
from app.models.governance import ActionStatus, AuditEvent, ReviewDecision
from app.services.action_service import ActionService, InvalidStatusTransition
from app.services.audit_service import (
    AUDIT_EVENT_TYPES,
    ENTITY_ACTION,
    ENTITY_IMPACT_ASSESSMENT,
    EVENT_ACTION_CREATED,
    EVENT_ACTION_STATUS_CHANGED,
    EVENT_ACTION_UPDATED,
    EVENT_REVIEW_FILED,
    AuditService,
)
from app.services.review_service import ReviewService


async def _events(org_id: str, **filters):
    async with AsyncSessionLocal() as session:
        return await AuditService.list_events(
            session, organization_id=org_id, **filters
        )


async def _count_events() -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(AuditEvent))


@pytest.mark.asyncio
async def test_filing_a_review_records_the_decision_and_both_states(
    demo_org, seeded_assessment
):
    async with AsyncSessionLocal() as session:
        review = await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=seeded_assessment["assessment_id"],
            reviewer_id=seeded_assessment["user_id"],
            decision=ReviewDecision.ACCEPT,
            notes="Looks right.",
        )

    events = await _events(demo_org.id, event_type=EVENT_REVIEW_FILED)
    assert len(events) == 1
    event = events[0]
    assert event.entity_type == ENTITY_IMPACT_ASSESSMENT
    assert event.entity_id == seeded_assessment["assessment_id"]
    assert event.actor_id == seeded_assessment["user_id"]

    payload = json.loads(event.payload)
    assert payload["decision"] == "ACCEPT"
    assert payload["review_id"] == review.id
    assert payload["previous_state"] == "COMPLETED"
    assert payload["new_state"] == "REVIEWED"
    # The note's presence is recorded; the note itself is not duplicated here.
    assert payload["has_notes"] is True
    assert "Looks right." not in (event.payload or "")


@pytest.mark.asyncio
async def test_raising_and_then_moving_an_action_records_both(demo_org, seeded_assessment):
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="Update the electronic labeling",
            impact_item_id=seeded_assessment["impact_item_id"],
            actor_id=seeded_assessment["user_id"],
        )

    created = await _events(demo_org.id, event_type=EVENT_ACTION_CREATED)
    assert len(created) == 1
    assert created[0].entity_type == ENTITY_ACTION
    assert created[0].entity_id == action.id
    assert json.loads(created[0].payload)["status"] == "OPEN"

    async with AsyncSessionLocal() as session:
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action.id,
            new_status=ActionStatus.IN_PROGRESS,
            actor_id=seeded_assessment["user_id"],
        )

    moved = await _events(demo_org.id, event_type=EVENT_ACTION_STATUS_CHANGED)
    assert len(moved) == 1
    assert json.loads(moved[0].payload) == {"from": "OPEN", "to": "IN_PROGRESS"}


@pytest.mark.asyncio
async def test_a_refused_transition_records_nothing(demo_org, seeded_assessment):
    """
    The guarantee the design exists for. COMPLETED is terminal, so the move below is
    refused -- and the trail must not claim it happened.
    """
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="Close out the assessment",
            actor_id=seeded_assessment["user_id"],
        )
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action.id,
            new_status=ActionStatus.COMPLETED,
            actor_id=seeded_assessment["user_id"],
        )

    before = await _count_events()

    async with AsyncSessionLocal() as session:
        with pytest.raises(InvalidStatusTransition):
            await ActionService.transition_status(
                session,
                organization_id=demo_org.id,
                action_id=action.id,
                new_status=ActionStatus.OPEN,
                actor_id=seeded_assessment["user_id"],
            )

    assert await _count_events() == before


@pytest.mark.asyncio
async def test_re_sending_the_current_status_is_not_recorded_as_a_change(
    demo_org, seeded_assessment
):
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="No-op transition",
            actor_id=seeded_assessment["user_id"],
        )

    before = await _count_events()

    async with AsyncSessionLocal() as session:
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action.id,
            new_status=ActionStatus.OPEN,
            actor_id=seeded_assessment["user_id"],
        )

    assert await _count_events() == before


@pytest.mark.asyncio
async def test_an_edit_records_the_field_names_not_the_values(
    demo_org, seeded_assessment
):
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="Original title",
            actor_id=seeded_assessment["user_id"],
        )

    async with AsyncSessionLocal() as session:
        await ActionService.update_action(
            session,
            organization_id=demo_org.id,
            action_id=action.id,
            title="Revised title",
            description="Some detail that should not appear in the trail.",
            actor_id=seeded_assessment["user_id"],
        )

    edits = await _events(demo_org.id, event_type=EVENT_ACTION_UPDATED)
    assert len(edits) == 1
    assert sorted(json.loads(edits[0].payload)["changed"]) == ["description", "title"]
    assert "Revised title" not in (edits[0].payload or "")


@pytest.mark.asyncio
async def test_a_status_move_through_the_patch_path_is_recorded_as_a_status_change(
    demo_org, seeded_assessment
):
    """The partial-update path is not a back door around the trail either."""
    async with AsyncSessionLocal() as session:
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="Patched into progress",
            actor_id=seeded_assessment["user_id"],
        )

    async with AsyncSessionLocal() as session:
        await ActionService.update_action(
            session,
            organization_id=demo_org.id,
            action_id=action.id,
            status=ActionStatus.BLOCKED,
            actor_id=seeded_assessment["user_id"],
        )

    moved = await _events(demo_org.id, event_type=EVENT_ACTION_STATUS_CHANGED)
    assert len(moved) == 1
    assert json.loads(moved[0].payload) == {"from": "OPEN", "to": "BLOCKED"}


@pytest.mark.asyncio
async def test_every_emitted_event_type_is_a_declared_one(demo_org, seeded_assessment):
    """
    Guards the vocabulary against drift: the trail is only filterable if what is
    written is what clients are told can be written.
    """
    async with AsyncSessionLocal() as session:
        await ReviewService.create_review(
            session,
            organization_id=demo_org.id,
            impact_assessment_id=seeded_assessment["assessment_id"],
            reviewer_id=seeded_assessment["user_id"],
            decision=ReviewDecision.MODIFY,
        )
        action = await ActionService.create_action(
            session,
            organization_id=demo_org.id,
            title="Vocabulary check",
            actor_id=seeded_assessment["user_id"],
        )
        await ActionService.transition_status(
            session,
            organization_id=demo_org.id,
            action_id=action.id,
            new_status=ActionStatus.CANCELLED,
            actor_id=seeded_assessment["user_id"],
        )

    for event in await _events(demo_org.id):
        assert event.event_type in AUDIT_EVENT_TYPES
