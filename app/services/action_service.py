"""
Remediation actions arising from a reviewed impact (Phase 7).

An action is what the organization commits to doing about an impact item. Like reviews,
every query here is scoped to an organization, and the status field is governed by an
explicit state machine rather than by whatever the caller sends.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governance import (
    ACTION_TRANSITIONS,
    Action,
    ActionPriority,
    ActionStatus,
)
from app.models.impact import ImpactAssessment, ImpactItem
from app.models.user import User
from app.services.audit_service import (
    ENTITY_ACTION,
    EVENT_ACTION_CREATED,
    EVENT_ACTION_STATUS_CHANGED,
    EVENT_ACTION_UPDATED,
    AuditService,
)


class InvalidStatusTransition(Exception):
    """A status change that the action state machine does not allow."""


class ActionService:
    """Organization-scoped operations over Action."""

    # -- validation helpers ------------------------------------------------------------

    @staticmethod
    async def _resolve_owner(
        session: AsyncSession, organization_id: str, owner_id: str
    ) -> None:
        """An action can only be owned by a member of the owning organization."""
        owner = (
            await session.execute(
                select(User).where(
                    User.id == owner_id, User.organization_id == organization_id
                )
            )
        ).scalars().first()
        if owner is None:
            raise ValueError(f"User {owner_id} not found")

    @staticmethod
    async def _resolve_impact_item(
        session: AsyncSession, organization_id: str, impact_item_id: str
    ) -> None:
        """
        An action can only hang off an impact item this organization owns.

        ImpactItem carries no organization_id of its own, so ownership is established
        through its parent assessment. Skipping this join would let one tenant attach
        work to another tenant's findings.
        """
        item = (
            await session.execute(
                select(ImpactItem)
                .join(
                    ImpactAssessment,
                    ImpactItem.impact_assessment_id == ImpactAssessment.id,
                )
                .where(
                    ImpactItem.id == impact_item_id,
                    ImpactAssessment.organization_id == organization_id,
                )
            )
        ).scalars().first()
        if item is None:
            raise ValueError(f"Impact item {impact_item_id} not found")

    # -- commands ----------------------------------------------------------------------

    @staticmethod
    async def create_action(
        session: AsyncSession,
        *,
        organization_id: str,
        title: str,
        description: Optional[str] = None,
        owner_id: Optional[str] = None,
        impact_item_id: Optional[str] = None,
        priority: ActionPriority = ActionPriority.MEDIUM,
        due_date: Optional[datetime] = None,
        actor_id: Optional[str] = None,
    ) -> Action:
        """
        Raise an action.

        `actor_id` is who is doing this, for the audit trail, and is distinct from
        `owner_id`, who is being asked to do the work. Neither is required, but an
        action raised with no actor records no attributable author.
        """
        if owner_id is not None:
            await ActionService._resolve_owner(session, organization_id, owner_id)
        if impact_item_id is not None:
            await ActionService._resolve_impact_item(
                session, organization_id, impact_item_id
            )

        action = Action(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            owner_id=owner_id,
            impact_item_id=impact_item_id,
            title=title,
            description=description,
            status=ActionStatus.OPEN,
            priority=priority,
            due_date=due_date,
        )
        session.add(action)
        AuditService.record(
            session,
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=EVENT_ACTION_CREATED,
            entity_type=ENTITY_ACTION,
            entity_id=action.id,
            payload={
                "title": title,
                "status": action.status.value,
                "priority": priority.value,
                "impact_item_id": impact_item_id,
                "owner_id": owner_id,
                "due_date": due_date,
            },
        )
        await session.commit()
        await session.refresh(action)
        return action

    @staticmethod
    async def update_action(
        session: AsyncSession,
        *,
        organization_id: str,
        action_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        owner_id: Optional[str] = None,
        impact_item_id: Optional[str] = None,
        priority: Optional[ActionPriority] = None,
        due_date: Optional[datetime] = None,
        status: Optional[ActionStatus] = None,
        actor_id: Optional[str] = None,
    ) -> Action:
        """
        Apply a partial update. `status` goes through the same transition check as
        transition_status, so there is no back door around the state machine.

        Two audit events can come out of one call, because a status move and a field
        edit are different things to a reader of the trail: the status change is
        recorded with its before and after, and any other edited fields are recorded
        by name. A call that changes nothing records nothing.
        """
        action = await ActionService.get_action(
            session, organization_id=organization_id, action_id=action_id
        )
        if action is None:
            raise ValueError(f"Action {action_id} not found")

        if owner_id is not None:
            await ActionService._resolve_owner(session, organization_id, owner_id)
            action.owner_id = owner_id
        if impact_item_id is not None:
            await ActionService._resolve_impact_item(
                session, organization_id, impact_item_id
            )
            action.impact_item_id = impact_item_id

        # Field names only -- the values are readable from the action itself, and the
        # trail should say what was touched rather than duplicate the record.
        changed: list[str] = []
        if owner_id is not None:
            changed.append("owner_id")
        if impact_item_id is not None:
            changed.append("impact_item_id")
        if title is not None:
            action.title = title
            changed.append("title")
        if description is not None:
            action.description = description
            changed.append("description")
        if priority is not None:
            action.priority = priority
            changed.append("priority")
        if due_date is not None:
            action.due_date = due_date
            changed.append("due_date")

        previous_status = action.status
        if status is not None:
            # Raises before anything is recorded, so a refused transition leaves no
            # event -- and, because nothing is committed, no field edit either.
            ActionService._apply_status(action, status)
            if action.status != previous_status:
                AuditService.record(
                    session,
                    organization_id=organization_id,
                    actor_id=actor_id,
                    event_type=EVENT_ACTION_STATUS_CHANGED,
                    entity_type=ENTITY_ACTION,
                    entity_id=action.id,
                    payload={
                        "from": previous_status.value,
                        "to": action.status.value,
                    },
                )

        if changed:
            AuditService.record(
                session,
                organization_id=organization_id,
                actor_id=actor_id,
                event_type=EVENT_ACTION_UPDATED,
                entity_type=ENTITY_ACTION,
                entity_id=action.id,
                payload={"changed": changed},
            )

        await session.commit()
        await session.refresh(action)
        return action

    @staticmethod
    def _apply_status(action: Action, new_status: ActionStatus) -> None:
        """
        Move an action along the state machine, maintaining completed_at.

        A no-op transition is allowed so that a client re-sending the current status is
        not treated as an error. Everything else must be declared in ACTION_TRANSITIONS.
        """
        current = action.status
        if new_status == current:
            return
        if new_status not in ACTION_TRANSITIONS[current]:
            raise InvalidStatusTransition(
                f"Cannot move an action from {current.value} to {new_status.value}"
            )
        action.status = new_status
        action.completed_at = (
            datetime.now(timezone.utc) if new_status == ActionStatus.COMPLETED else None
        )

    @staticmethod
    async def transition_status(
        session: AsyncSession,
        *,
        organization_id: str,
        action_id: str,
        new_status: ActionStatus,
        actor_id: Optional[str] = None,
    ) -> Action:
        action = await ActionService.get_action(
            session, organization_id=organization_id, action_id=action_id
        )
        if action is None:
            raise ValueError(f"Action {action_id} not found")

        previous_status = action.status
        # Raises on an illegal move before anything is recorded, so the trail never
        # gains an event for a transition the state machine refused.
        ActionService._apply_status(action, new_status)
        # A client re-sending the current status is allowed and is not a change, so it
        # is not recorded as one.
        if action.status != previous_status:
            AuditService.record(
                session,
                organization_id=organization_id,
                actor_id=actor_id,
                event_type=EVENT_ACTION_STATUS_CHANGED,
                entity_type=ENTITY_ACTION,
                entity_id=action.id,
                payload={"from": previous_status.value, "to": action.status.value},
            )
        await session.commit()
        await session.refresh(action)
        return action

    # -- queries -----------------------------------------------------------------------

    @staticmethod
    async def get_action(
        session: AsyncSession, *, organization_id: str, action_id: str
    ) -> Optional[Action]:
        return (
            await session.execute(
                select(Action).where(
                    Action.id == action_id,
                    Action.organization_id == organization_id,
                )
            )
        ).scalars().first()

    @staticmethod
    async def list_actions(
        session: AsyncSession,
        *,
        organization_id: str,
        owner_id: Optional[str] = None,
        impact_item_id: Optional[str] = None,
        status: Optional[ActionStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Action]:
        """Actions owned by this organization, newest first, optionally filtered."""
        query = select(Action).where(Action.organization_id == organization_id)
        if owner_id is not None:
            query = query.where(Action.owner_id == owner_id)
        if impact_item_id is not None:
            query = query.where(Action.impact_item_id == impact_item_id)
        if status is not None:
            query = query.where(Action.status == status)

        result = await session.execute(
            query.order_by(Action.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_actions_due_within(
        session: AsyncSession, *, organization_id: str, days: int = 7
    ) -> List[Action]:
        """Open work with a due date inside the window, soonest first."""
        threshold = datetime.now(timezone.utc) + timedelta(days=days)
        result = await session.execute(
            select(Action)
            .where(
                Action.organization_id == organization_id,
                Action.due_date.isnot(None),
                Action.due_date <= threshold,
                Action.status.notin_(
                    [ActionStatus.COMPLETED, ActionStatus.CANCELLED]
                ),
            )
            .order_by(Action.due_date.asc())
        )
        return list(result.scalars().all())
