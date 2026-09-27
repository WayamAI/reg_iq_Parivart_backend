from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# Document Analysis Schemas
class DocumentSummary(BaseModel):
    title: str
    document_type: str
    jurisdiction: str
    summary: str
    key_topics: List[str]
    effective_date: Optional[datetime] = None
    publication_date: Optional[datetime] = None

class ExtractedChange(BaseModel):
    section: str
    change_type: str  # Use ChangeType enum values
    summary: str
    previous_text: Optional[str] = None
    new_text: Optional[str] = None
    source_reference: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

class ExtractedObligation(BaseModel):
    text: str
    category: str  # Use ObligationCategory enum values
    applicability: Optional[str] = None
    jurisdiction: Optional[str] = None
    effective_date: Optional[datetime] = None
    source_page: Optional[str] = None
    source_section: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)

class ApplicabilityAssessment(BaseModel):
    product_id: Optional[str] = None
    market_id: Optional[str] = None
    process_id: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str

class DocumentAnalysisResult(BaseModel):
    document_summary: DocumentSummary
    changes: List[ExtractedChange] = []
    obligations: List[ExtractedObligation] = []
    applicability: List[ApplicabilityAssessment] = []
    confidence: float = Field(ge=0.0, le=1.0)
    prompt_version: str
    ai_model: str
    analyzed_at: datetime

# Impact Analysis Schemas
class ImpactItemResult(BaseModel):
    obligation_id: str
    entity_type: str  # product, market, process, control
    entity_id: str
    impact_level: str  # NO_MATCH, POTENTIALLY_AFFECTED, REQUIRES_REVIEW, HIGH_IMPACT, MEDIUM_IMPACT, LOW_IMPACT
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: List[str] = []

class ImpactAnalysisResult(BaseModel):
    impact_items: List[ImpactItemResult]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    prompt_version: str
    ai_model: str
    analyzed_at: datetime