"""
The audit trail (Phase 8).

An audit event answers five questions about a change that has already happened:
who did it, what they did, to which entity, when, and what changed. Three
properties make the answers trustworthy rather than decorative:

  * **An event joins the caller's unit of work.** `record()` adds a row to the
    session and deliberately does not commit. The change and the event that
    describes it therefore succeed or fail together: a refused action transition
    leaves no event claiming it happened, and a recorded event is never orphaned
    from the change it describes.
  * **Every query is scoped to an organization.** An event is read back only by
    the tenant whose data it concerns, never via the URL alone.
  * **Events are only ever inserted.** There is no update and no delete, here or
    over HTTP. A trail that can be rewritten is not a trail.

`event_type` is a free `String(100)` in the model rather than a database enum,
and stays a plain string on the wire. The vocabulary below is the canonical set
this application writes, but reading is deliberately tolerant: an event written
by an older or newer revision still reads back and still renders, instead of
failing serialisation because a value is absent from a Python enum.
"""

import json
import uuid
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.governance import AuditEvent

# --- Vocabulary ------------------------------------------------------------------------
# Entity types name the record an event is *about*, so a caller can ask "the history of
# this assessment" without knowing which events exist.
ENTITY_USER = "USER"
ENTITY_REGULATORY_DOCUMENT = "REGULATORY_DOCUMENT"
ENTITY_IMPACT_ASSESSMENT = "IMPACT_ASSESSMENT"
ENTITY_IMPACT_REPORT = "IMPACT_REPORT"
ENTITY_ACTION = "ACTION"

EVENT_USER_SIGNED_IN = "USER_SIGNED_IN"
EVENT_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
EVENT_DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"
EVENT_IMPACT_ASSESSMENT_CREATED = "IMPACT_ASSESSMENT_CREATED"
EVENT_IMPACT_ASSESSMENT_REANALYZED = "IMPACT_ASSESSMENT_REANALYZED"
EVENT_REPORT_GENERATED = "REPORT_GENERATED"
EVENT_REVIEW_FILED = "REVIEW_FILED"
EVENT_ACTION_CREATED = "ACTION_CREATED"
EVENT_ACTION_UPDATED = "ACTION_UPDATED"
EVENT_ACTION_STATUS_CHANGED = "ACTION_STATUS_CHANGED"
EVENT_EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"

# Exposed so a client can offer a filter over the vocabulary without hardcoding it, and
# so a test can assert that every emitted type is a declared one.
AUDIT_EVENT_TYPES: tuple[str, ...] = (
    EVENT_USER_SIGNED_IN,
    EVENT_DOCUMENT_UPLOADED,
    EVENT_DOCUMENT_PROCESSED,
    EVENT_IMPACT_ASSESSMENT_CREATED,
    EVENT_IMPACT_ASSESSMENT_REANALYZED,
    EVENT_REPORT_GENERATED,
    EVENT_REVIEW_FILED,
    EVENT_ACTION_CREATED,
    EVENT_ACTION_UPDATED,
    EVENT_ACTION_STATUS_CHANGED,
    EVENT_EVIDENCE_ATTACHED,
)

AUDIT_ENTITY_TYPES: tuple[str, ...] = (
    ENTITY_USER,
    ENTITY_REGULATORY_DOCUMENT,
    ENTITY_IMPACT_ASSESSMENT,
    ENTITY_IMPACT_REPORT,
    ENTITY_ACTION,
)


class AuditService:
    """Organization-scoped operations over AuditEvent."""

    @staticmethod
    def record(
        session: AsyncSession,
        *,
        organization_id: str,
        actor_id: Optional[str],
        event_type: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> AuditEvent:
        """
        Add an audit event to the caller's transaction.

        Deliberately synchronous and deliberately without a commit: the caller owns
        the unit of work, and this row belongs to it. Committing here would let an
        event outlive a change that was then rolled back, which is the one failure
        an audit trail cannot have.

        `payload` carries ids, enum values, changed field *names* and before/after
        states -- never a credential, a token, a password hash, file bytes or
        document text. It is serialised to JSON because the column is `Text`.
        """
        event = AuditEvent(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=json.dumps(payload, default=str) if payload is not None else None,
        )
        session.add(event)
        return event

    @staticmethod
    async def list_events(
        session: AsyncSession,
        *,
        organization_id: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """
        This organization's audit events, newest first.

        The actor is eager-loaded because the point of the trail is *who*, and a
        page of rows each lazy-loading its own user would be a query per row.
        """
        query = (
            select(AuditEvent)
            .where(AuditEvent.organization_id == organization_id)
            .options(selectinload(AuditEvent.actor))
        )
        if entity_type is not None:
            query = query.where(AuditEvent.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditEvent.entity_id == entity_id)
        if actor_id is not None:
            query = query.where(AuditEvent.actor_id == actor_id)
        if event_type is not None:
            query = query.where(AuditEvent.event_type == event_type)
        if since is not None:
            query = query.where(AuditEvent.created_at >= since)
        if until is not None:
            query = query.where(AuditEvent.created_at <= until)

        result = await session.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_event(
        session: AsyncSession, *, organization_id: str, event_id: str
    ) -> Optional[AuditEvent]:
        return (
            (
                await session.execute(
                    select(AuditEvent)
                    .where(
                        AuditEvent.id == event_id,
                        AuditEvent.organization_id == organization_id,
                    )
                    .options(selectinload(AuditEvent.actor))
                )
            )
            .scalars()
            .first()
        )
