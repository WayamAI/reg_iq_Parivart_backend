"""
Evidence attached to remediation actions (Phase 8).

Upload, list, read and download. Evidence attaches to an action, so there is no
generic "attach to anything" endpoint -- the table does not support one and
pretending otherwise would invent a graph the data cannot back.
"""

from typing import List, Optional
from urllib.parse import quote

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.permissions import require_operate
from app.api.schemas.evidence import EvidenceResponse
from app.db.database import get_db
from app.models.governance import Evidence
from app.models.user import User
from app.services.evidence_service import EvidenceService

logger = structlog.get_logger()

router = APIRouter(prefix="/evidence", tags=["Evidence"])


def _to_response(evidence: Evidence) -> EvidenceResponse:
    """`storage_key` is never included -- see the schema's module docstring."""
    uploader = evidence.uploaded_by
    return EvidenceResponse(
        id=evidence.id,
        action_id=evidence.action_id,
        uploaded_by_id=evidence.uploaded_by_id,
        uploaded_by_name=uploader.name if uploader else None,
        uploaded_by_email=uploader.email if uploader else None,
        filename=evidence.filename,
        sha256=evidence.sha256,
        description=evidence.description,
        created_at=evidence.created_at,
    )


@router.post(
    "/upload", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED
)
async def upload_evidence(
    file: UploadFile = File(...),
    action_id: str = Form(...),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operate),
):
    """
    Attach a file to an action as evidence.

    The uploader and the tenant come from the access token, never the form, so a
    caller cannot file evidence as somebody else. An action belonging to another
    tenant is reported as missing, exactly like one that does not exist -- and the
    check happens before the file is stored, so such a request writes nothing.
    """
    try:
        evidence = await EvidenceService.attach(
            db,
            organization_id=current_user.organization_id,
            action_id=action_id,
            file_data=file.file,
            file_name=file.filename or "evidence",
            content_type=file.content_type or "application/octet-stream",
            description=description,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return _to_response(evidence)


@router.get("/", response_model=List[EvidenceResponse])
async def list_evidence(
    action_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """This organization's evidence, newest first, optionally for one action."""
    rows = await EvidenceService.list_evidence(
        db,
        organization_id=current_user.organization_id,
        action_id=action_id,
        skip=skip,
        limit=limit,
    )
    return [_to_response(row) for row in rows]


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    evidence = await EvidenceService.get(
        db, organization_id=current_user.organization_id, evidence_id=evidence_id
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return _to_response(evidence)


@router.get("/{evidence_id}/download")
async def download_evidence(
    evidence_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Stream the stored file back.

    The record is resolved and its tenant checked first; only then is the storage
    key used. That ordering is the reason `storage_key` need never leave the server.
    """
    evidence = await EvidenceService.get(
        db, organization_id=current_user.organization_id, evidence_id=evidence_id
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")

    try:
        handle = await EvidenceService.open_file(evidence)
    except FileNotFoundError:
        # The row exists but the bytes are gone. That is a real and distinguishable
        # failure -- a 404 here would wrongly say the evidence was never filed.
        logger.error(
            "evidence_file_missing",
            evidence_id=evidence.id,
            organization_id=current_user.organization_id,
        )
        raise HTTPException(
            status_code=410,
            detail="This evidence record exists, but its stored file is no longer available",
        )

    filename = evidence.filename or "evidence"
    return StreamingResponse(
        handle,
        media_type="application/octet-stream",
        headers={
            # RFC 5987 form, so a non-ASCII filename survives the round trip.
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(filename)}"
            )
        },
    )
