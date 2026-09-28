from sqlalchemy import Column, String, DateTime, func, Boolean, ForeignKey
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    REGULATORY_MANAGER = "REGULATORY_MANAGER"
    COMPLIANCE_MANAGER = "COMPLIANCE_MANAGER"
    REVIEWER = "REVIEWER"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(50), default=UserRole.VIEWER.value)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    organization = relationship("Organization", back_populates="users")
    actions = relationship("Action", back_populates="owner")
    reviews = relationship("ImpactReview", back_populates="reviewer")
    audit_events = relationship("AuditEvent", foreign_keys="AuditEvent.actor_id", back_populates="actor")