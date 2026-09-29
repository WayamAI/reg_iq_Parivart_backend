from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class ActionStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class ActionPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class ReviewDecision(str, enum.Enum):
    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"


# Allowed Action status transitions. COMPLETED and CANCELLED are terminal: an action that
# has been closed is never silently reopened, because downstream evidence and audit records
# reference the closed state.
ACTION_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.OPEN: frozenset(
        {ActionStatus.IN_PROGRESS, ActionStatus.BLOCKED, ActionStatus.COMPLETED, ActionStatus.CANCELLED}
    ),
    ActionStatus.IN_PROGRESS: frozenset(
        {ActionStatus.OPEN, ActionStatus.BLOCKED, ActionStatus.COMPLETED, ActionStatus.CANCELLED}
    ),
    ActionStatus.BLOCKED: frozenset(
        {ActionStatus.OPEN, ActionStatus.IN_PROGRESS, ActionStatus.COMPLETED, ActionStatus.CANCELLED}
    ),
    ActionStatus.COMPLETED: frozenset(),
    ActionStatus.CANCELLED: frozenset(),
}

TERMINAL_ACTION_STATUSES = frozenset({ActionStatus.COMPLETED, ActionStatus.CANCELLED})


class Action(Base):
    __tablename__ = "actions"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), index=True)
    impact_item_id = Column(String(36), ForeignKey("impact_items.id"), index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(
        Enum(ActionStatus, native_enum=False), default=ActionStatus.OPEN, nullable=False
    )
    priority = Column(
        Enum(ActionPriority, native_enum=False), default=ActionPriority.MEDIUM, nullable=False
    )
    due_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    # Set when the action first enters COMPLETED, cleared for no other status.
    completed_at = Column(DateTime(timezone=True))

    organization = relationship("Organization", back_populates="actions")
    owner = relationship("User", back_populates="actions")
    impact_item = relationship("ImpactItem", back_populates="actions")
    evidence = relationship("Evidence", back_populates="action")

class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    action_id = Column(String(36), ForeignKey("actions.id"), index=True)
    uploaded_by_id = Column(String(36), ForeignKey("users.id"), index=True)
    filename = Column(String(500))
    storage_key = Column(String(500))
    sha256 = Column(String(64), index=True)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="evidence")
    action = relationship("Action", back_populates="evidence")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"), index=True)
    event_type = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), index=True)
    entity_id = Column(String(36), index=True)
    payload = Column(Text)  # JSON formatted event detail
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="audit_events")
    actor = relationship("User", foreign_keys=[actor_id], back_populates="audit_events")

class ImpactReview(Base):
    """
    A human decision recorded against an ImpactAssessment.

    Rows here are append-only. A reviewer who changes their mind files a *new* review; the
    earlier one is never rewritten, so the decision trail stays reconstructable. Each row
    records the assessment status before (`previous_state`) and after (`new_state`) the
    decision it carries.
    """

    __tablename__ = "impact_reviews"

    id = Column(String(36), primary_key=True, index=True)
    # Denormalised from the parent assessment so every tenant-scoped query can filter on
    # this table directly instead of relying on a join to stay correct.
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    impact_assessment_id = Column(String(36), ForeignKey("impact_assessments.id"), index=True, nullable=False)
    reviewer_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    decision = Column(Enum(ReviewDecision, native_enum=False), nullable=False)
    notes = Column(Text)
    previous_state = Column(String(50))
    new_state = Column(String(50))
    reviewed_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="reviews")
    impact_assessment = relationship("ImpactAssessment", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")
