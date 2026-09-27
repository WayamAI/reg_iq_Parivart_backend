from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.services.document_service import upload_and_create_document
from app.api.schemas.document import DocumentUploadResponse, DocumentResponse
from app.api.dependencies.auth import get_current_user
from app.models.user import User
from typing import Optional

router = APIRouter(prefix="/documents", tags=["Regulatory Documents"])

@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    document_type: str = Form("OTHER"),
    jurisdiction: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    authority_id: str = Form(...),
    source_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Validate that the authority and source exist (optional, but good practice)
    # For now, we assume they are valid; we can add checks later.

    # Check that the current user's organization matches the organization we are uploading to?
    # In a multi-tenant system, we might want to ensure the user can only upload to their own organization.
    # However, the authority and source are global, so we need to know which organization the document belongs to.
    # We don't have an organization_id in the form. We should get it from the current user.
    organization_id = current_user.organization_id

    # Call the service to upload and create the document
    document, is_duplicate = await upload_and_create_document(
        db=db,
        organization_id=organization_id,
        authority_id=authority_id,
        source_id=source_id,
        file_data=file.file,  # UploadFile has a file attribute that is a SpooledTemporaryFile (binary)
        file_name=file.filename,
        content_type=file.content_type or "application/octet-stream",
        title=title,
        description=description,
        document_type=document_type,
        jurisdiction=jurisdiction,
        country=country,
        source_url=source_url,
    )

    # Return the response
    return DocumentUploadResponse(
        document_id=document.id,
        sha256=document.sha256,
        message="Document uploaded successfully" if not is_duplicate else "Document already exists (duplicate)",
        is_duplicate=is_duplicate,
    )

# Additional endpoints for documents can be added here (get, list, delete, etc.)
@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Only return documents for the current user's organization
    result = await db.execute(
        select(RegulatoryDocument)
        .where(RegulatoryDocument.organization_id == current_user.organization_id)
        .offset(skip)
        .limit(limit)
    )
    documents = result.scalars().all()
    return documents

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(RegulatoryDocument)
        .where(
            RegulatoryDocument.id == document_id,
            RegulatoryDocument.organization_id == current_user.organization_id
        )
    )
    document = result.scalars().first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document

from sqlalchemy import select