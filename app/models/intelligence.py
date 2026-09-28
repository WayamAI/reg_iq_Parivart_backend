from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, func, Integer, Numeric, Boolean
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class ChangeType(str, enum.Enum):
    NEW_REQUIREMENT = "NEW_REQUIREMENT"
    REQUIREMENT_CHANGE = "REQUIREMENT_CHANGE"
    DELETED_REQUIREMENT = "DELETED_REQUIREMENT"
    SCOPE_CHANGE = "SCOPE_CHANGE"
    DEADLINE_CHANGE = "DEADLINE_CHANGE"
    LABELING_CHANGE = "LABELING_CHANGE"
    REPORTING_CHANGE = "REPORTING_CHANGE"
    PROCESS_CHANGE = "PROCESS_CHANGE"
    SAFETY_CHANGE = "SAFETY_CHANGE"
    DEFINITION_CHANGE = "DEFINITION_CHANGE"
    OTHER = "OTHER"

class ObligationCategory(str, enum.Enum):
    LABELING = "LABELING"
    MANUFACTURING = "MANUFACTURING"
    QUALITY = "QUALITY"
    SAFETY = "SAFETY"
    REPORTING = "REPORTING"
    REGISTRATION = "REGISTRATION"
    SUBMISSION = "SUBMISSION"
    POST_MARKET = "POST_MARKET"
    CLINICAL = "CLINICAL"
    PACKAGING = "PACKAGING"
    DATA = "DATA"
    CYBERSECURITY = "CYBERSECURITY"
    RECORDKEEPING = "RECORDKEEPING"
    OTHER = "OTHER"

class RegulatoryChange(Base):
    __tablename__ = "regulatory_changes"

    id = Column(String(36), primary_key=True, index=True)
    document_id = Column(String(36), ForeignKey("regulatory_documents.id"), index=True)
    version_id = Column(String(36), ForeignKey("regulatory_versions.id"), index=True)
    section = Column(String(500))
    change_type = Column(Enum(ChangeType, native_enum=False), nullable=False)
    summary = Column(Text, nullable=False)
    previous_text = Column(Text)
    new_text = Column(Text)
    source_reference = Column(String(500))
    confidence = Column(Numeric(3, 2))
    prompt_version = Column(String(100))
    ai_model = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("RegulatoryDocument", back_populates="changes")
    version = relationship("RegulatoryVersion", back_populates="changes")
    obligations = relationship("RegulatoryObligation", back_populates="change")
    impact_assessments = relationship("ImpactAssessment", back_populates="regulatory_change")

class RegulatoryObligation(Base):
    __tablename__ = "regulatory_obligations"

    id = Column(String(36), primary_key=True, index=True)
    change_id = Column(String(36), ForeignKey("regulatory_changes.id"), index=True)
    document_id = Column(String(36), ForeignKey("regulatory_documents.id"), index=True)
    text = Column(Text, nullable=False)
    category = Column(Enum(ObligationCategory, native_enum=False), nullable=False)
    applicability = Column(Text)
    jurisdiction = Column(String(100))
    effective_date = Column(DateTime(timezone=True))
    source_page = Column(String(100))
    source_section = Column(String(200))
    confidence = Column(Numeric(3, 2))
    prompt_version = Column(String(100))
    ai_model = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    change = relationship("RegulatoryChange", back_populates="obligations")
    document = relationship("RegulatoryDocument")
    impact_items = relationship("ImpactItem", back_populates="obligation")
    impact_items = relationship("ImpactItem", back_populates="obligation")