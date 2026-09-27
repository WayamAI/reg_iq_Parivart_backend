from sqlalchemy import Column, String, Text, DateTime, func
from sqlalchemy.orm import relationship
from app.db.base import Base

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    industry = Column(String(100))
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    users = relationship("User", back_populates="organization")
    products = relationship("Product", back_populates="organization")
    markets = relationship("Market", back_populates="organization")
    processes = relationship("Process", back_populates="organization")
    controls = relationship("Control", back_populates="organization")
    registrations = relationship("Registration", back_populates="organization")
    regulatory_documents = relationship("RegulatoryDocument", back_populates="organization")
    impact_assessments = relationship("ImpactAssessment", back_populates="organization")
    impact_reports = relationship("ImpactReport", back_populates="organization")
    actions = relationship("Action", back_populates="organization")
    evidence = relationship("Evidence", back_populates="organization")
    audit_events = relationship("AuditEvent", back_populates="organization")
