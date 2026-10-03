from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, delete, func
from typing import List, Optional
import uuid

from app.db.database import get_db
from app.models.portfolio import Process
from app.api.schemas.portfolio import (
    ProcessCreate,
    ProcessUpdate,
    ProcessResponse,
)
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.permissions import require_configure
from app.models.user import User

router = APIRouter(prefix="/processes", tags=["Portfolio - Processes"])

@router.post("/", response_model=ProcessResponse, status_code=status.HTTP_201_CREATED)
async def create_process(
    process_in: ProcessCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    process = Process(
        id=str(uuid.uuid4()),
        organization_id=current_user.organization_id,
        **process_in.dict()
    )
    db.add(process)
    await db.commit()
    await db.refresh(process)
    return process

@router.get("/", response_model=List[ProcessResponse])
async def list_processes(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Process)
        .where(Process.organization_id == current_user.organization_id)
        .offset(skip)
        .limit(limit)
    )
    processes = result.scalars().all()
    return processes

@router.get("/{process_id}", response_model=ProcessResponse)
async def get_process(
    process_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Process).where(
            Process.id == process_id,
            Process.organization_id == current_user.organization_id
        )
    )
    process = result.scalars().first()
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    return process

@router.patch("/{process_id}", response_model=ProcessResponse)
async def update_process(
    process_id: str,
    process_in: ProcessUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    result = await db.execute(
        select(Process).where(
            Process.id == process_id,
            Process.organization_id == current_user.organization_id
        )
    )
    process = result.scalars().first()
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")

    update_data = process_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(process, field, value)

    await db.commit()
    await db.refresh(process)
    return process

@router.delete("/{process_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_process(
    process_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_configure)
):
    result = await db.execute(
        select(Process).where(
            Process.id == process_id,
            Process.organization_id == current_user.organization_id
        )
    )
    process = result.scalars().first()
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")

    await db.delete(process)
    await db.commit()
    return None