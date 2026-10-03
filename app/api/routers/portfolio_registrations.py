from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional
import uuid

from app.db.database import get_db
from app.models.portfolio import Registration, RegistrationStatus, Product, Market
from app.models.regulatory import RegulatoryAuthority
from app.api.schemas.portfolio import (
    RegistrationCreate,
    RegistrationUpdate,
    RegistrationResponse,
)
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.permissions import require_configure
from app.models.user import User

router = APIRouter(prefix="/registrations", tags=["Portfolio - Registrations"])

@router.post("/", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED)
async def create_registration(
    registration_in: RegistrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    # Verify that the product, market, and authority exist and belong to the organization (for product and market)
    # Product check
    product_result = await db.execute(
        select(Product).where(
            Product.id == registration_in.product_id,
            Product.organization_id == current_user.organization_id
        )
    )
    if not product_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product not found or does not belong to this organization"
        )

    # Market check
    market_result = await db.execute(
        select(Market).where(
            Market.id == registration_in.market_id,
            Market.organization_id == current_user.organization_id
        )
    )
    if not market_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Market not found or does not belong to this organization"
        )

    # Authority check (global, so just check existence)
    authority_result = await db.execute(
        select(RegulatoryAuthority).where(RegulatoryAuthority.id == registration_in.authority_id)
    )
    if not authority_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authority not found"
        )

    registration = Registration(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        **registration_in.dict()
    )
    db.add(registration)
    await db.commit()
    await db.refresh(registration)
    return registration

@router.get("/", response_model=List[RegistrationResponse])
async def list_registrations(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[RegistrationStatus] = Query(None),
    product_id: Optional[str] = Query(None),
    market_id: Optional[str] = Query(None),
    authority_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Registration).where(Registration.organization_id == current_user.organization_id)
    if status:
        query = query.where(Registration.status == status)
    if product_id:
        query = query.where(Registration.product_id == product_id)
    if market_id:
        query = query.where(Registration.market_id == market_id)
    if authority_id:
        query = query.where(Registration.authority_id == authority_id)
    result = await db.execute(query.offset(skip).limit(limit))
    registrations = result.scalars().all()
    return registrations

@router.get("/{registration_id}", response_model=RegistrationResponse)
async def get_registration(
    registration_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Registration).where(
            Registration.id == registration_id,
            Registration.organization_id == current_user.organization_id
        )
    )
    registration = result.scalars().first()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")
    return registration

@router.patch("/{registration_id}", response_model=RegistrationResponse)
async def update_registration(
    registration_id: str,
    registration_in: RegistrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    result = await db.execute(
        select(Registration).where(
            Registration.id == registration_id,
            Registration.organization_id == current_user.organization_id
        )
    )
    registration = result.scalars().first()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")

    update_data = registration_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(registration, field, value)

    await db.commit()
    await db.refresh(registration)
    return registration

@router.delete("/{registration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration(
    registration_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    result = await db.execute(
        select(Registration).where(
            Registration.id == registration_id,
            Registration.organization_id == current_user.organization_id
        )
    )
    registration = result.scalars().first()
    if not registration:
        raise HTTPException(status_code=404, detail="Registration not found")

    await db.delete(registration)
    await db.commit()
    return None