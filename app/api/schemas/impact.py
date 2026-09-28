from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime
from app.models.impact import (
    AIEnrichmentStatus,
    EntityType,
    ImpactAssessmentStatus,
    ImpactLevel,
    ImpactReportStatus,
)

class ImpactItemBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    obligation_id: Optional[str] = None
    entity_type: EntityType
    entity_id: str
    impact_level: ImpactLevel
    confidence: float
    match_score: float
    reason: str
    match_types: Optional[str] = None
    evidence: Optional[str] = None
    status: str = "ACTIVE"

class ImpactItemResponse(ImpactItemBase):
    id: str
    impact_assessment_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

class ImpactAssessmentBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    regulatory_change_id: str
    status: ImpactAssessmentStatus = ImpactAssessmentStatus.PENDING
    overall_impact_level: ImpactLevel = ImpactLevel.REQUIRES_REVIEW
    overall_confidence: float = 0.85
    summary: Optional[str] = None
    analysis_version: int = 1

class ImpactAssessmentCreate(BaseModel):
    regulatory_change_id: str
    force_reanalyze: bool = False

class ImpactAssessmentResponse(ImpactAssessmentBase):
    id: str
    organization_id: str
    engine_version: Optional[str] = None
    # AI provenance. ai_model/ai_narrative are populated only by a genuinely
    # successful enrichment pass; ai_enrichment_status always says what happened.
    ai_model: Optional[str] = None
    prompt_version: Optional[str] = None
    ai_enrichment_status: AIEnrichmentStatus = AIEnrichmentStatus.DISABLED
    ai_enrichment_error: Optional[str] = None
    ai_narrative: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: List[ImpactItemResponse] = []

class ImpactReportCreate(BaseModel):
    impact_assessment_id: str
    title: Optional[str] = None

class ImpactReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    impact_assessment_id: str
    regulatory_change_id: str
    title: str
    summary: Optional[str] = None
    status: ImpactReportStatus
    version: int
    report_data: Any
    created_at: datetime
    updated_at: Optional[datetime] = None
