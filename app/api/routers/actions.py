from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.schemas.action import (
    ActionCreate,
    ActionResponse,
    ActionStatusUpdate,
    ActionUpdate,
)
from app.db.database import get_db
from app.models.governance import ActionStatus
from app.models.user import User
from app.services.action_service import ActionService, InvalidStatusTransition

logger = structlog.get_logger()

router = APIRouter(prefix="/actions", tags=["Actions"])


@router.post("/", response_model=ActionResponse, status_code=status.HTTP_201_CREATED)
async def create_action(
    payload: ActionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Open a remediation action.

    The owning organization is the authenticated user's, so an action can never be
    created inside another tenant. An owner or impact item outside that tenant is
    reported as missing.
    """
    try:
        action = await ActionService.create_action(
            db,
            organization_id=current_user.organization_id,
            title=payload.title,
            description=payload.description,
            owner_id=payload.owner_id,
            impact_item_id=payload.impact_item_id,
            priority=payload.priority,
            due_date=payload.due_date,
            actor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return action


@router.get("/", response_model=List[ActionResponse])
async def list_actions(
    owner_id: Optional[str] = None,
    impact_item_id: Optional[str] = None,
    action_status: Optional[ActionStatus] = Query(default=None, alias="status"),
    due_within_days: Optional[int] = Query(default=None, ge=1, le=365),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The organization's actions, newest first, or the due-date window when asked."""
    if due_within_days is not None:
        return await ActionService.list_actions_due_within(
            db, organization_id=current_user.organization_id, days=due_within_days
        )
    return await ActionService.list_actions(
        db,
        organization_id=current_user.organization_id,
        owner_id=owner_id,
        impact_item_id=impact_item_id,
        status=action_status,
        skip=skip,
        limit=limit,
    )


@router.get("/{action_id}", response_model=ActionResponse)
async def get_action(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = await ActionService.get_action(
        db, organization_id=current_user.organization_id, action_id=action_id
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.patch("/{action_id}", response_model=ActionResponse)
async def update_action(
    action_id: str,
    payload: ActionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        action = await ActionService.update_action(
            db,
            organization_id=current_user.organization_id,
            action_id=action_id,
            title=payload.title,
            description=payload.description,
            owner_id=payload.owner_id,
            impact_item_id=payload.impact_item_id,
            priority=payload.priority,
            due_date=payload.due_date,
            status=payload.status,
            actor_id=current_user.id,
        )
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return action


@router.patch("/{action_id}/status", response_model=ActionResponse)
async def transition_action_status(
    action_id: str,
    payload: ActionStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move an action along its state machine.

    A transition the machine does not allow -- reopening closed work, for instance --
    is a 409 against current state, not a validation error.
    """
    try:
        action = await ActionService.transition_status(
            db,
            organization_id=current_user.organization_id,
            action_id=action_id,
            new_status=payload.status,
            actor_id=current_user.id,
        )
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return action
