import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete
from typing import List, Optional

from app.db.database import get_db
from app.models.regulatory import RegulatoryAuthority
from app.api.schemas.regulatory import (
    AuthorityCreate,
    AuthorityUpdate,
    AuthorityResponse,
)
from app.api.dependencies.auth import get_current_user

router = APIRouter(prefix="/authorities", tags=["Regulatory Authorities"])

@router.post("/", response_model=AuthorityResponse, status_code=status.HTTP_201_CREATED)
async def create_authority(
    authority_in: AuthorityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    # Ensure the user has permission (ADMIN or REGULATORY_MANAGER)
    # For now we allow any authenticated user, but we can add role checks later
    # (see docs/security/AUTHORIZATION_GAPS.md).
    #
    # id is a String(36) primary key with no column default (see app/db/base.py: Base
    # is a plain declarative_base with no id mixin), so an omitted id inserts NULL and
    # the insert fails -- the same class of bug already fixed once for document
    # creation (commit f4b6853).
    authority = RegulatoryAuthority(id=str(uuid.uuid4()), **authority_in.dict())
    db.add(authority)
    await db.commit()
    await db.refresh(authority)
    return authority

@router.get("/", response_model=List[AuthorityResponse])
async def list_authorities(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    result = await db.execute(select(RegulatoryAuthority).offset(skip).limit(limit))
    authorities = result.scalars().all()
    return authorities

@router.get("/{authority_id}", response_model=AuthorityResponse)
async def get_authority(
    authority_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    result = await db.execute(select(RegulatoryAuthority).where(RegulatoryAuthority.id == authority_id))
    authority = result.scalars().first()
    if not authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    return authority

@router.patch("/{authority_id}", response_model=AuthorityResponse)
async def update_authority(
    authority_id: str,
    authority_in: AuthorityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    result = await db.execute(select(RegulatoryAuthority).where(RegulatoryAuthority.id == authority_id))
    authority = result.scalars().first()
    if not authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    update_data = authority_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(authority, field, value)
    await db.commit()
    await db.refresh(authority)
    return authority

@router.delete("/{authority_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_authority(
    authority_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    result = await db.execute(select(RegulatoryAuthority).where(RegulatoryAuthority.id == authority_id))
    authority = result.scalars().first()
    if not authority:
        raise HTTPException(status_code=404, detail="Authority not found")
    await db.delete(authority)
    await db.commit()
    return None