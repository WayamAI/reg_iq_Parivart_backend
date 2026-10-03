import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import BinaryIO, Tuple, Optional
from app.storage.base import LocalStorage
from app.db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.document import RegulatoryDocument
from app.services.audit_service import (
    ENTITY_REGULATORY_DOCUMENT,
    EVENT_DOCUMENT_UPLOADED,
    AuditService,
)
from app.core.config import settings

# Initialize storage (using local storage for now)
storage = LocalStorage(base_path=getattr(settings, 'STORAGE_PATH', './storage'))

async def compute_sha256(file_data: BinaryIO) -> str:
    """Compute SHA-256 hash of file data."""
    # Reset file pointer to beginning
    file_data.seek(0)
    sha256_hash = hashlib.sha256()
    for chunk in iter(lambda: file_data.read(4096), b""):
        sha256_hash.update(chunk)
    file_data.seek(0)  # Reset again for future reads
    return sha256_hash.hexdigest()

async def check_duplicate_sha256(
    sha256: str, db: AsyncSession, organization_id: str
) -> Optional[RegulatoryDocument]:
    """
    Check if a document with the same SHA-256 already exists for this organization.

    Scoped to organization_id: this used to query sha256 alone, which meant a second
    organization uploading byte-identical content (e.g. a public regulatory PDF) was
    silently handed back the FIRST organization's document id as "your duplicate" --
    a cross-tenant existence/identity leak, and a real document for the second
    organization was never created. Deduplication is per-tenant, not global.
    """
    result = await db.execute(
        select(RegulatoryDocument).where(
            RegulatoryDocument.sha256 == sha256,
            RegulatoryDocument.organization_id == organization_id,
        )
    )
    return result.scalars().first()

async def create_document_record(
    db: AsyncSession,
    *,
    organization_id: str,
    authority_id: str,
    source_id: str,
    title: str,
    description: Optional[str],
    document_type: str,
    jurisdiction: Optional[str],
    country: Optional[str],
    source_url: Optional[str],
    storage_key: str,
    mime_type: str,
    file_size: int,
    sha256: str,
    retrieved_at: Optional[datetime] = None,
    actor_id: Optional[str] = None,
) -> RegulatoryDocument:
    """Create a new RegulatoryDocument record."""
    if retrieved_at is None:
        # tz-aware: retrieved_at is DateTime(timezone=True), and a naive value is
        # stored as if it were local time.
        retrieved_at = datetime.now(timezone.utc)

    document = RegulatoryDocument(
        # RegulatoryDocument.id is a String(36) primary key with no column default,
        # and Base is a plain declarative_base() with no id mixin, so an omitted id
        # is inserted as NULL and the insert fails.
        id=str(uuid.uuid4()),
        organization_id=organization_id,
        authority_id=authority_id,
        source_id=source_id,
        title=title,
        description=description,
        document_type=document_type,
        jurisdiction=jurisdiction,
        country=country,
        source_url=source_url,
        storage_key=storage_key,
        mime_type=mime_type,
        file_size=file_size,
        sha256=sha256,
        retrieved_at=retrieved_at,
        processing_status="DISCOVERED",  # Start with discovered
    )
    db.add(document)
    # Recorded before the commit, so the document and the event announcing it are one
    # unit of work. Only a genuinely new document reaches here: a duplicate returns
    # earlier and records nothing, because nothing was added.
    AuditService.record(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        event_type=EVENT_DOCUMENT_UPLOADED,
        entity_type=ENTITY_REGULATORY_DOCUMENT,
        entity_id=document.id,
        payload={
            "title": title,
            "document_type": document_type,
            "sha256": sha256,
            "authority_id": authority_id,
            "source_id": source_id,
            "file_size": file_size,
        },
    )
    await db.commit()
    await db.refresh(document)
    return document

async def upload_and_create_document(
    db: AsyncSession,
    *,
    organization_id: str,
    authority_id: str,
    source_id: str,
    file_data: BinaryIO,
    file_name: str,
    content_type: str,
    title: str,
    description: Optional[str] = None,
    document_type: str = "OTHER",
    jurisdiction: Optional[str] = None,
    country: Optional[str] = None,
    source_url: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> Tuple[RegulatoryDocument, bool]:
    """
    Upload a file, check for duplicates, and create a document record.
    Returns (document, is_duplicate) where is_duplicate is True if the document already existed.
    """
    # Compute SHA-256
    sha256 = await compute_sha256(file_data)

    # Check for duplicate, scoped to this organization only.
    existing = await check_duplicate_sha256(sha256, db, organization_id)
    if existing:
        # Return the existing document and mark as duplicate
        return existing, True

    # Upload to storage
    storage_key = await storage.upload_file(file_data, file_name, content_type)

    # Get file size (we need to reset the file pointer after reading for hash)
    file_data.seek(0, os.SEEK_END)
    file_size = file_data.tell()
    file_data.seek(0)

    # Create document record
    document = await create_document_record(
        db=db,
        organization_id=organization_id,
        authority_id=authority_id,
        source_id=source_id,
        title=title,
        description=description,
        document_type=document_type,
        jurisdiction=jurisdiction,
        country=country,
        source_url=source_url,
        storage_key=storage_key,
        mime_type=content_type,
        file_size=file_size,
        sha256=sha256,
        actor_id=actor_id,
    )

    return document, False