"""
The audit trail, read-only.

There is deliberately no POST, PATCH or DELETE here. Audit events are written by
the services as a side effect of a real change, never posted by a client: a trail
a caller can write to is a trail that proves nothing, and one a caller can edit is
not a trail at all. The only way to add an event is to make the change it describes.
"""

import json
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.schemas.audit import AuditEventResponse, AuditEventTypesResponse
from app.db.database import get_db
from app.models.governance import AuditEvent
from app.models.user import User
from app.services.audit_service import (
    AUDIT_ENTITY_TYPES,
    AUDIT_EVENT_TYPES,
    AuditService,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/audit", tags=["Audit Trail"])


def _to_response(event: AuditEvent) -> AuditEventResponse:
    """
    Shape one event for the wire.

    `payload` is stored as a JSON string in a Text column; it is parsed here so a
    client receives an object, the same treatment report_data gets. A payload that
    does not parse is reported as absent rather than raising: a malformed detail on
    a historical row must not make the rest of the trail unreadable.
    """
    payload = None
    if event.payload:
        try:
            parsed = json.loads(event.payload)
            # Only an object is a payload. A bare string or list would not match the
            # declared response type, and coercing one would invent structure.
            payload = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            logger.warning("audit_payload_unparseable", event_id=event.id)

    actor = event.actor
    return AuditEventResponse(
        id=event.id,
        actor_id=event.actor_id,
        actor_name=actor.name if actor else None,
        actor_email=actor.email if actor else None,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        payload=payload,
        created_at=event.created_at,
    )


# Declared before /{event_id} so the literal path is not captured as an id.
@router.get("/event-types", response_model=AuditEventTypesResponse)
async def list_event_types(current_user: User = Depends(get_current_user)):
    """
    The vocabulary this backend writes, so a client can offer a filter without
    hardcoding a list that would drift from the server.

    This describes what can be written, not what this organization has. An event
    type appearing here with no matching rows is the normal case.
    """
    return AuditEventTypesResponse(
        event_types=list(AUDIT_EVENT_TYPES),
        entity_types=list(AUDIT_ENTITY_TYPES),
    )


@router.get("/", response_model=List[AuditEventResponse])
async def list_audit_events(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    This organization's audit trail, newest first.

    `entity_type` + `entity_id` together answer "the history of this record", which
    is how a detail screen links to its own provenance.
    """
    events = await AuditService.list_events(
        db,
        organization_id=current_user.organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        event_type=event_type,
        since=since,
        until=until,
        skip=skip,
        limit=limit,
    )
    return [_to_response(event) for event in events]


@router.get("/{event_id}", response_model=AuditEventResponse)
async def get_audit_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = await AuditService.get_event(
        db, organization_id=current_user.organization_id, event_id=event_id
    )
    # An event belonging to another tenant reads as missing, never as forbidden --
    # the same rule every other resource here follows, so the response does not
    # confirm that an id exists elsewhere.
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return _to_response(event)
