from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Optional, List
from app.models.regulatory import ConnectorType, SourceType, IngestionStatus
from datetime import datetime

# Authority Schemas
class AuthorityBase(BaseModel):
    name: str
    short_name: str
    jurisdiction: Optional[str] = None
    country: Optional[str] = None
    website: Optional[HttpUrl] = None
    description: Optional[str] = None
    is_active: bool = True

class AuthorityCreate(AuthorityBase):
    pass

class AuthorityUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    jurisdiction: Optional[str] = None
    country: Optional[str] = None
    website: Optional[HttpUrl] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class AuthorityResponse(AuthorityBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Source Schemas
class SourceBase(BaseModel):
    authority_id: str
    name: str
    description: Optional[str] = None
    jurisdiction: Optional[str] = None
    country: Optional[str] = None
    source_type: SourceType
    connector_type: ConnectorType
    url: Optional[HttpUrl] = None
    enabled: bool = True
    schedule: Optional[str] = None

    # A DOCUMENT/manual source has no URL to poll. The column is nullable, so "no URL" is
    # NULL -- but rows exist that store it as an empty string, and HttpUrl rejects "" as
    # "input is empty". That surfaced as a 500 (ResponseValidationError) on GET
    # /regulatory/sources/ rather than as a bad request, because it failed on the way out.
    @field_validator("url", mode="before")
    @classmethod
    def _empty_url_is_absent(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

class SourceCreate(SourceBase):
    pass

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    jurisdiction: Optional[str] = None
    country: Optional[str] = None
    source_type: Optional[SourceType] = None
    connector_type: Optional[ConnectorType] = None
    url: Optional[HttpUrl] = None
    enabled: Optional[bool] = None
    schedule: Optional[str] = None

class SourceResponse(SourceBase):
    id: str
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Ingestion Run Schemas
class IngestionRunBase(BaseModel):
    status: IngestionStatus
    documents_discovered: int = 0
    documents_downloaded: int = 0
    documents_processed: int = 0
    documents_failed: int = 0
    error: Optional[str] = None

class IngestionRunCreate(IngestionRunBase):
    source_id: str

class IngestionRunResponse(IngestionRunBase):
    id: str
    source_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True