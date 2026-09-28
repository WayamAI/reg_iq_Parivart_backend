from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class ActionStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"

class ReviewDecision(str, enum.Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_INFO = "NEEDS_INFO"

class Action(Base):
    __tablename__ = "actions"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), index=True)
    impact_item_id = Column(String(36), ForeignKey("impact_items.id"), index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(Enum(ActionStatus, native_enum=False), default=ActionStatus.OPEN)
    due_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

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
    __tablename__ = "impact_reviews"

    id = Column(String(36), primary_key=True, index=True)
    impact_assessment_id = Column(String(36), ForeignKey("impact_assessments.id"), index=True, nullable=False)
    reviewer_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    decision = Column(Enum(ReviewDecision, native_enum=False), nullable=False)
    notes = Column(Text)
    reviewed_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    impact_assessment = relationship("ImpactAssessment", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")
