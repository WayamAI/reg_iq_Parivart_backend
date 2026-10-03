"""
Wire shapes for the audit trail.

`event_type` and `entity_type` are plain strings, not enums, matching the columns
behind them. The canonical vocabulary lives in `app.services.audit_service`; keeping
the wire type open means an event written by another revision of this application
still reads back and still renders, rather than failing serialisation because its
value is missing from a Python enum. A client maps the values it knows to labels and
falls back to showing the raw value.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    """
    One recorded change: who, what, which entity, when, and what changed.

    The actor is reported as an id *and* as the name and email resolved from it, so a
    reader does not have to look up a UUID to learn who acted. `actor_*` are null for
    an event with no attributable user.
    """

    id: str
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_email: Optional[str] = None
    event_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    # Stored as a JSON string in a Text column and parsed here, so a client receives an
    # object rather than a string it has to parse itself -- the same treatment
    # ImpactReportResponse gives report_data.
    payload: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class AuditEventTypesResponse(BaseModel):
    """
    The vocabulary this application writes.

    Served so a client can build a filter without hardcoding a list that would drift
    from the backend. It describes what *can* be written, not what is present.
    """

    event_types: list[str]
    entity_types: list[str]
