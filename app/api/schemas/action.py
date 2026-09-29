from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.governance import ActionPriority, ActionStatus


class ActionCreate(BaseModel):
    """
    A new remediation action.

    organization_id is deliberately absent: the owning tenant comes from the
    authenticated user, not from the request body, so a caller cannot create work
    inside another organization.
    """

    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=10_000)
    owner_id: Optional[str] = None
    impact_item_id: Optional[str] = None
    priority: ActionPriority = ActionPriority.MEDIUM
    due_date: Optional[datetime] = None


class ActionUpdate(BaseModel):
    """Partial update. Omitted fields are left alone."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=10_000)
    owner_id: Optional[str] = None
    impact_item_id: Optional[str] = None
    priority: Optional[ActionPriority] = None
    due_date: Optional[datetime] = None
    status: Optional[ActionStatus] = None


class ActionStatusUpdate(BaseModel):
    """
    A status change on its own.

    Carried in the body rather than the query string so the transition is an explicit,
    loggable payload like every other write in the API.
    """

    status: ActionStatus


class ActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    owner_id: Optional[str] = None
    impact_item_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: ActionStatus
    priority: ActionPriority
    due_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
