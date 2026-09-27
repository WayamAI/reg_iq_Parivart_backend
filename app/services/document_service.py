import hashlib
import os
from datetime import datetime
from typing import BinaryIO, Tuple, Optional
from app.storage.base import LocalStorage
from app.db.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.document import RegulatoryDocument
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

async def check_duplicate_sha256(sha256: str, db: AsyncSession) -> Optional[RegulatoryDocument]:
    """Check if a document with the same SHA-256 already exists."""
    result = await db.execute(select(RegulatoryDocument).where(RegulatoryDocument.sha256 == sha256))
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
) -> RegulatoryDocument:
    """Create a new RegulatoryDocument record."""
    if retrieved_at is None:
        retrieved_at = datetime.utcnow()

    document = RegulatoryDocument(
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
) -> Tuple[RegulatoryDocument, bool]:
    """
    Upload a file, check for duplicates, and create a document record.
    Returns (document, is_duplicate) where is_duplicate is True if the document already existed.
    """
    # Compute SHA-256
    sha256 = await compute_sha256(file_data)

    # Check for duplicate
    existing = await check_duplicate_sha256(sha256, db)
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
    )

    return document, False