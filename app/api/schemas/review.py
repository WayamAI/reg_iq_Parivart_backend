from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.governance import ReviewDecision


class ReviewCreate(BaseModel):
    """
    A review decision filed against an assessment.

    Neither the organization nor the reviewer appears here. Both are taken from the
    authenticated user, so a caller cannot file a review as somebody else or against
    another tenant's assessment by editing the request body.
    """

    impact_assessment_id: str = Field(min_length=1)
    decision: ReviewDecision
    notes: Optional[str] = Field(default=None, max_length=10_000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    impact_assessment_id: str
    reviewer_id: str
    decision: ReviewDecision
    notes: Optional[str] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
