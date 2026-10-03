from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional
import uuid

from app.db.database import get_db
from app.models.portfolio import Market, MarketStatus
from app.api.schemas.portfolio import (
    MarketCreate,
    MarketUpdate,
    MarketResponse,
)
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.permissions import require_configure
from app.models.user import User

router = APIRouter(prefix="/markets", tags=["Portfolio - Markets"])

@router.post("/", response_model=MarketResponse, status_code=status.HTTP_201_CREATED)
async def create_market(
    market_in: MarketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    market = Market(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        **market_in.dict()
    )
    db.add(market)
    await db.commit()
    await db.refresh(market)
    return market

@router.get("/", response_model=List[MarketResponse])
async def list_markets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[MarketStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Market).where(Market.organization_id == current_user.organization_id)
    if status:
        query = query.where(Market.status == status)
    result = await db.execute(query.offset(skip).limit(limit))
    markets = result.scalars().all()
    return markets

@router.get("/{market_id}", response_model=MarketResponse)
async def get_market(
    market_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Market).where(
            Market.id == market_id,
            Market.organization_id == current_user.organization_id
        )
    )
    market = result.scalars().first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return market

@router.patch("/{market_id}", response_model=MarketResponse)
async def update_market(
    market_id: str,
    market_in: MarketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    result = await db.execute(
        select(Market).where(
            Market.id == market_id,
            Market.organization_id == current_user.organization_id
        )
    )
    market = result.scalars().first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    update_data = market_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(market, field, value)

    await db.commit()
    await db.refresh(market)
    return market

@router.delete("/{market_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_market(
    market_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    result = await db.execute(
        select(Market).where(
            Market.id == market_id,
            Market.organization_id == current_user.organization_id
        )
    )
    market = result.scalars().first()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")

    await db.delete(market)
    await db.commit()
    return None