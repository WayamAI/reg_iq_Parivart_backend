from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional
import uuid

from app.db.database import get_db
from app.models.portfolio import Control, ControlCategory, ControlStatus
from app.api.schemas.portfolio import (
    ControlCreate,
    ControlUpdate,
    ControlResponse,
)
from app.api.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/controls", tags=["Portfolio - Controls"])

@router.post("/", response_model=ControlResponse, status_code=status.HTTP_201_CREATED)
async def create_control(
    control_in: ControlCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    control = Control(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        **control_in.dict()
    )
    db.add(control)
    await db.commit()
    await db.refresh(control)
    return control

@router.get("/", response_model=List[ControlResponse])
async def list_controls(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    category: Optional[ControlCategory] = Query(None),
    status: Optional[ControlStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Control).where(Control.organization_id == current_user.organization_id)
    if category:
        query = query.where(Control.category == category)
    if status:
        query = query.where(Control.status == status)
    result = await db.execute(query.offset(skip).limit(limit))
    controls = result.scalars().all()
    return controls

@router.get("/{control_id}", response_model=ControlResponse)
async def get_control(
    control_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Control).where(
            Control.id == control_id,
            Control.organization_id == current_user.organization_id
        )
    )
    control = result.scalars().first()
    if not control:
        raise HTTPException(status_code=404, detail="Control not found")
    return control

@router.patch("/{control_id}", response_model=ControlResponse)
async def update_control(
    control_id: str,
    control_in: ControlUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Control).where(
            Control.id == control_id,
            Control.organization_id == current_user.organization_id
        )
    )
    control = result.scalars().first()
    if not control:
        raise HTTPException(status_code=404, detail="Control not found")

    update_data = control_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(control, field, value)

    await db.commit()
    await db.refresh(control)
    return control

@router.delete("/{control_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_control(
    control_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Control).where(
            Control.id == control_id,
            Control.organization_id == current_user.organization_id
        )
    )
    control = result.scalars().first()
    if not control:
        raise HTTPException(status_code=404, detail="Control not found")

    await db.delete(control)
    await db.commit()
    return None