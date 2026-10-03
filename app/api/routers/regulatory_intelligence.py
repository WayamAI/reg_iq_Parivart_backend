"""
Regulatory changes and obligations, read-only (Phase 8 companion).

This closes the one visible break in the product's narrative. An impact assessment
carries a `regulatory_change_id`, and until now no endpoint could resolve it: the
UI could show the id and the engine's summary of the change, but could not link
through to the change itself or list the obligations behind a match. "What changed?"
had no screen.

**Tenancy.** Neither `regulatory_changes` nor `regulatory_obligations` has an
`organization_id`. Ownership runs through the document: a change belongs to the
tenant that owns `regulatory_changes.document_id`. Every query here therefore joins
`regulatory_documents` and filters on its `organization_id`, the same way
`ActionService._resolve_impact_item` establishes ownership of an impact item through
its parent assessment. Skipping that join would let any tenant read every tenant's
extracted regulatory intelligence.

**Read-only.** The document-processing pipeline owns these rows. They are what it
extracted from a source document, not user-entered data, so there is no create,
update or delete: hand-editing an extracted obligation would destroy the provenance
that makes it worth anything.
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.schemas.intelligence import (
    RegulatoryChangeResponse,
    RegulatoryObligationResponse,
)
from app.db.database import get_db
from app.models.document import RegulatoryDocument
from app.models.intelligence import (
    ChangeType,
    ObligationCategory,
    RegulatoryChange,
    RegulatoryObligation,
)
from app.models.user import User

logger = structlog.get_logger()

router = APIRouter(tags=["Regulatory Intelligence"])


def _changes_for_org(organization_id: str):
    """
    Base query for changes this organization can see.

    The join is the tenant boundary, not a convenience -- see the module docstring.
    """
    return (
        select(RegulatoryChange)
        .join(
            RegulatoryDocument,
            RegulatoryChange.document_id == RegulatoryDocument.id,
        )
        .where(RegulatoryDocument.organization_id == organization_id)
    )


def _obligations_for_org(organization_id: str):
    return (
        select(RegulatoryObligation)
        .join(
            RegulatoryDocument,
            RegulatoryObligation.document_id == RegulatoryDocument.id,
        )
        .where(RegulatoryDocument.organization_id == organization_id)
    )


# --- changes ---------------------------------------------------------------------------


@router.get("/changes/", response_model=List[RegulatoryChangeResponse])
async def list_regulatory_changes(
    document_id: Optional[str] = None,
    change_type: Optional[ChangeType] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Changes extracted from this organization's documents, newest first."""
    query = _changes_for_org(current_user.organization_id)
    if document_id is not None:
        query = query.where(RegulatoryChange.document_id == document_id)
    if change_type is not None:
        query = query.where(RegulatoryChange.change_type == change_type)

    result = await db.execute(
        query.order_by(RegulatoryChange.created_at.desc(), RegulatoryChange.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/changes/{change_id}", response_model=RegulatoryChangeResponse)
async def get_regulatory_change(
    change_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    change = (
        (
            await db.execute(
                _changes_for_org(current_user.organization_id).where(
                    RegulatoryChange.id == change_id
                )
            )
        )
        .scalars()
        .first()
    )
    # Another tenant's change reads as missing, never as forbidden.
    if change is None:
        raise HTTPException(status_code=404, detail="Regulatory change not found")
    return change


@router.get(
    "/changes/{change_id}/obligations",
    response_model=List[RegulatoryObligationResponse],
)
async def list_obligations_for_change(
    change_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    The obligations this change creates.

    Ownership is established on the change first, so an unknown or cross-tenant id
    is a 404 rather than an empty list -- "this change has no obligations" and "you
    cannot see this change" are different answers and should not look alike.
    """
    change = (
        (
            await db.execute(
                _changes_for_org(current_user.organization_id).where(
                    RegulatoryChange.id == change_id
                )
            )
        )
        .scalars()
        .first()
    )
    if change is None:
        raise HTTPException(status_code=404, detail="Regulatory change not found")

    result = await db.execute(
        select(RegulatoryObligation)
        .where(RegulatoryObligation.change_id == change_id)
        .order_by(RegulatoryObligation.created_at.asc(), RegulatoryObligation.id.asc())
    )
    return list(result.scalars().all())


# --- obligations -----------------------------------------------------------------------


@router.get("/obligations/", response_model=List[RegulatoryObligationResponse])
async def list_regulatory_obligations(
    regulatory_change_id: Optional[str] = None,
    document_id: Optional[str] = None,
    category: Optional[ObligationCategory] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obligations extracted from this organization's documents."""
    query = _obligations_for_org(current_user.organization_id)
    if regulatory_change_id is not None:
        query = query.where(RegulatoryObligation.change_id == regulatory_change_id)
    if document_id is not None:
        query = query.where(RegulatoryObligation.document_id == document_id)
    if category is not None:
        query = query.where(RegulatoryObligation.category == category)

    result = await db.execute(
        query.order_by(
            RegulatoryObligation.created_at.desc(), RegulatoryObligation.id.desc()
        )
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/obligations/{obligation_id}", response_model=RegulatoryObligationResponse)
async def get_regulatory_obligation(
    obligation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obligation = (
        (
            await db.execute(
                _obligations_for_org(current_user.organization_id).where(
                    RegulatoryObligation.id == obligation_id
                )
            )
        )
        .scalars()
        .first()
    )
    if obligation is None:
        raise HTTPException(status_code=404, detail="Obligation not found")
    return obligation
