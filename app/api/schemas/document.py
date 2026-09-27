from pydantic import BaseModel, Field
from typing import Optional
from app.models.document import DocumentProcessingStatus, DocumentType
from datetime import datetime

class DocumentBase(BaseModel):
    title: str
    description: Optional[str] = None
    document_type: DocumentType = DocumentType.OTHER
    jurisdiction: Optional[str] = None
    country: Optional[str] = None
    source_url: Optional[str] = None

class DocumentCreate(DocumentBase):
    pass

class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[DocumentType] = None
    jurisdiction: Optional[str] = None
    country: Optional[str] = None
    source_url: Optional[str] = None
    processing_status: Optional[DocumentProcessingStatus] = None

class DocumentResponse(DocumentBase):
    id: str
    organization_id: str
    authority_id: str
    source_id: str
    storage_key: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    sha256: Optional[str] = None
    publication_date: Optional[datetime] = None
    effective_date: Optional[datetime] = None
    retrieved_at: datetime
    processing_status: DocumentProcessingStatus
    language: str = "en"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DocumentUploadResponse(BaseModel):
    document_id: str
    sha256: str
    message: str
    is_duplicate: bool = False