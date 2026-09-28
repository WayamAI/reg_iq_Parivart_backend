from sqlalchemy import Column, String, Text, DateTime, Enum, Boolean, ForeignKey, func, Integer
from sqlalchemy.orm import relationship
import enum
from app.db.base import Base

class ConnectorType(str, enum.Enum):
    RSS = "RSS"
    API = "API"
    WEB_SERVICE = "WEB_SERVICE"
    HTML = "HTML"
    DOCUMENT = "DOCUMENT"

class SourceType(str, enum.Enum):
    RSS = "RSS"
    API = "API"
    WEB_SERVICE = "WEB_SERVICE"
    HTML = "HTML"
    DOCUMENT = "DOCUMENT"

class IngestionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"

class RegulatoryAuthority(Base):
    __tablename__ = "regulatory_authorities"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    short_name = Column(String(50), unique=True, nullable=False, index=True)
    jurisdiction = Column(String(100))
    country = Column(String(100))
    website = Column(String(500))
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    sources = relationship("RegulatorySource", back_populates="authority")

class RegulatorySource(Base):
    __tablename__ = "regulatory_sources"

    id = Column(String(36), primary_key=True, index=True)
    authority_id = Column(String(36), ForeignKey("regulatory_authorities.id"), index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    jurisdiction = Column(String(100))
    country = Column(String(100))
    source_type = Column(Enum(SourceType, native_enum=False), nullable=False)
    connector_type = Column(Enum(ConnectorType, native_enum=False), nullable=False)
    url = Column(String(1000))
    enabled = Column(Boolean, default=True)
    schedule = Column(String(100))
    last_run_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    authority = relationship("RegulatoryAuthority", back_populates="sources")
    documents = relationship("RegulatoryDocument", back_populates="source")
    runs = relationship("IngestionRun", back_populates="source")

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id = Column(String(36), primary_key=True, index=True)
    source_id = Column(String(36), ForeignKey("regulatory_sources.id"), index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    status = Column(Enum(IngestionStatus, native_enum=False), default=IngestionStatus.QUEUED)
    documents_discovered = Column(Integer, default=0)
    documents_downloaded = Column(Integer, default=0)
    documents_processed = Column(Integer, default=0)
    documents_failed = Column(Integer, default=0)
    error = Column(Text)

    source = relationship("RegulatorySource", back_populates="runs")