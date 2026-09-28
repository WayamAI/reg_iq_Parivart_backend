from sqlalchemy import Column, String, Text, DateTime, Enum, ForeignKey, func, Integer, Boolean
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class DocumentProcessingStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"

class DocumentType(str, enum.Enum):
    REGULATION = "REGULATION"
    GUIDANCE = "GUIDANCE"
    NOTICE = "NOTICE"
    SAFETY_ALERT = "SAFETY_ALERT"
    STANDARD = "STANDARD"
    AMENDMENT = "AMENDMENT"
    RULE = "RULE"
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    OTHER = "OTHER"

class RegulatoryDocument(Base):
    __tablename__ = "regulatory_documents"

    id = Column(String(36), primary_key=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), index=True)
    authority_id = Column(String(36), ForeignKey("regulatory_authorities.id"), index=True)
    source_id = Column(String(36), ForeignKey("regulatory_sources.id"), index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    document_type = Column(Enum(DocumentType, native_enum=False), default=DocumentType.OTHER)
    jurisdiction = Column(String(100))
    country = Column(String(100))
    source_url = Column(String(1000))
    storage_key = Column(String(500))
    mime_type = Column(String(100))
    file_size = Column(Integer)
    sha256 = Column(String(64), unique=True, index=True)
    publication_date = Column(DateTime(timezone=True))
    effective_date = Column(DateTime(timezone=True))
    retrieved_at = Column(DateTime(timezone=True), server_default=func.now())
    processing_status = Column(Enum(DocumentProcessingStatus, native_enum=False), default=DocumentProcessingStatus.DISCOVERED)
    language = Column(String(10), default="en")
    extracted_text = Column(Text)  # The extracted text from the document
    parsed_at = Column(DateTime(timezone=True))  # When the text extraction was completed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="regulatory_documents")
    authority = relationship("RegulatoryAuthority")
    source = relationship("RegulatorySource", back_populates="documents")
    versions = relationship("RegulatoryVersion", back_populates="document")
    changes = relationship("RegulatoryChange", back_populates="document")

class RegulatoryVersion(Base):
    __tablename__ = "regulatory_versions"

    id = Column(String(36), primary_key=True, index=True)
    document_id = Column(String(36), ForeignKey("regulatory_documents.id"), index=True)
    version_number = Column(Integer, default=1)
    sha256 = Column(String(64), index=True)
    content_hash = Column(String(64))
    storage_key = Column(String(500))
    published_at = Column(DateTime(timezone=True))
    retrieved_at = Column(DateTime(timezone=True), server_default=func.now())
    is_current = Column(Boolean, default=True)
    previous_version_id = Column(String(36), ForeignKey("regulatory_versions.id"))

    document = relationship("RegulatoryDocument", back_populates="versions")
    changes = relationship("RegulatoryChange", back_populates="version")