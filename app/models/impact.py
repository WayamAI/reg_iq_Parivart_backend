from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, func, Integer, Numeric
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class ImpactAssessmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    REVIEWED = "REVIEWED"

class ImpactLevel(str, enum.Enum):
    NO_MATCH = "NO_MATCH"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    POTENTIALLY_AFFECTED = "POTENTIALLY_AFFECTED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"

class EntityType(str, enum.Enum):
    PRODUCT = "PRODUCT"
    MARKET = "MARKET"
    PROCESS = "PROCESS"
    CONTROL = "CONTROL"
    REGISTRATION = "REGISTRATION"

class MatchType(str, enum.Enum):
    JURISDICTION_MATCH = "JURISDICTION_MATCH"
    PRODUCT_CATEGORY_MATCH = "PRODUCT_CATEGORY_MATCH"
    PRODUCT_KEYWORD_MATCH = "PRODUCT_KEYWORD_MATCH"
    MARKET_MATCH = "MARKET_MATCH"
    PROCESS_MATCH = "PROCESS_MATCH"
    CONTROL_MATCH = "CONTROL_MATCH"
    REGISTRATION_MATCH = "REGISTRATION_MATCH"
    SEMANTIC_MATCH = "SEMANTIC_MATCH"
    AI_REVIEW = "AI_REVIEW"

class ImpactReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEWED = "REVIEWED"
    ARCHIVED = "ARCHIVED"

class AIEnrichmentStatus(str, enum.Enum):
    """
    Outcome of the *optional* AI enrichment pass for an assessment.

    The deterministic assessment is always produced without any provider call, so a
    non-SUCCESS value here never invalidates the assessment -- it records only that the
    narrative layer is absent and why. A failure is never recorded as a SUCCESS.
    """
    DISABLED = "DISABLED"                  # enrichment switched off (the default)
    SUCCESS = "SUCCESS"
    RATE_LIMITED = "RATE_LIMITED"          # provider returned 429
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"            # no provider registered / connection refused
    INVALID_RESPONSE = "INVALID_RESPONSE"  # empty, unparseable or off-schema response
    AUTH_ERROR = "AUTH_ERROR"              # 401 / 403
    PROVIDER_ERROR = "PROVIDER_ERROR"      # any other provider-side failure

class ImpactAssessment(Base):
    __tablename__ = "impact_assessments"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    regulatory_change_id = Column(String(36), ForeignKey("regulatory_changes.id"), index=True, nullable=False)
    status = Column(Enum(ImpactAssessmentStatus, native_enum=False), default=ImpactAssessmentStatus.PENDING)
    overall_impact_level = Column(Enum(ImpactLevel, native_enum=False), default=ImpactLevel.REQUIRES_REVIEW)
    overall_confidence = Column(Numeric(3, 2), default=0.80)
    summary = Column(Text)
    analysis_version = Column(Integer, default=1)
    engine_version = Column(String(50), default="v1.0")
    # AI provenance. These stay NULL for a purely deterministic run -- they are written
    # only by a genuinely successful enrichment pass.
    ai_model = Column(String(100))
    prompt_version = Column(String(100))
    ai_enrichment_status = Column(
        Enum(AIEnrichmentStatus, native_enum=False),
        default=AIEnrichmentStatus.DISABLED,
        nullable=False,
    )
    ai_enrichment_error = Column(Text)
    ai_narrative = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="impact_assessments")
    regulatory_change = relationship("RegulatoryChange", back_populates="impact_assessments")
    items = relationship("ImpactItem", back_populates="impact_assessment", cascade="all, delete-orphan")
    reports = relationship("ImpactReport", back_populates="impact_assessment", cascade="all, delete-orphan")
    reviews = relationship("ImpactReview", back_populates="impact_assessment", cascade="all, delete-orphan")

class ImpactItem(Base):
    __tablename__ = "impact_items"

    id = Column(String(36), primary_key=True, index=True)
    impact_assessment_id = Column(String(36), ForeignKey("impact_assessments.id"), index=True, nullable=False)
    obligation_id = Column(String(36), ForeignKey("regulatory_obligations.id"), index=True, nullable=True)
    entity_type = Column(Enum(EntityType, native_enum=False), nullable=False)
    entity_id = Column(String(36), index=True, nullable=False)
    impact_level = Column(Enum(ImpactLevel, native_enum=False), default=ImpactLevel.POTENTIALLY_AFFECTED)
    confidence = Column(Numeric(3, 2), default=0.85)
    match_score = Column(Numeric(3, 2), default=0.75)
    reason = Column(Text, nullable=False)
    # Comma-separated MatchType values that fired for this item, for cheap filtering.
    match_types = Column(String(500))
    evidence = Column(Text)  # JSON formatted evidence list / facts
    status = Column(String(50), default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    impact_assessment = relationship("ImpactAssessment", back_populates="items")
    obligation = relationship("RegulatoryObligation", back_populates="impact_items")
    actions = relationship("Action", back_populates="impact_item")

class ImpactReport(Base):
    __tablename__ = "impact_reports"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True, nullable=False)
    impact_assessment_id = Column(String(36), ForeignKey("impact_assessments.id"), index=True, nullable=False)
    regulatory_change_id = Column(String(36), ForeignKey("regulatory_changes.id"), index=True, nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text)
    status = Column(Enum(ImpactReportStatus, native_enum=False), default=ImpactReportStatus.GENERATED)
    version = Column(Integer, default=1)
    report_data = Column(Text, nullable=False)  # Stored JSON containing Fact, Source Evidence, System Interpretation, Human Decision
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="impact_reports")
    impact_assessment = relationship("ImpactAssessment", back_populates="reports")
    regulatory_change = relationship("RegulatoryChange")