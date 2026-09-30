from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid

from app.db.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User, UserRole
from app.models.organization import Organization
from app.api.schemas.auth import UserCreate, UserResponse, TokenResponse, OrganizationCreate
from app.api.dependencies.auth import get_current_user
from app.services.audit_service import (
    ENTITY_USER,
    EVENT_USER_SIGNED_IN,
    AuditService,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    org_in: OrganizationCreate,
    db: AsyncSession = Depends(get_db)
):
    # Check if user already exists
    user_check = await db.execute(select(User).where(User.email == user_in.email))
    if user_check.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if org slug already exists
    org_check = await db.execute(select(Organization).where(Organization.slug == org_in.slug))
    if org_check.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization slug already exists"
        )

    # Create Organization
    org_id = str(uuid.uuid4())
    db_org = Organization(
        id=org_id,
        name=org_in.name,
        slug=org_in.slug,
        industry=org_in.industry,
        description=org_in.description
    )
    db.add(db_org)

    # Create User
    user_id = str(uuid.uuid4())
    db_user = User(
        id=user_id,
        organization_id=org_id,
        name=user_in.name,
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        role=user_in.role
    )
    db.add(db_user)

    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalars().first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    access_token = create_access_token(data={"sub": user.email})

    # A successful sign-in is recorded; a failed one is not. Failed attempts belong in
    # the security log, not in a tenant-readable audit trail, and recording them here
    # would mean writing rows on behalf of a caller who has not authenticated.
    # The payload carries no token and no credential.
    AuditService.record(
        db,
        organization_id=user.organization_id,
        actor_id=user.id,
        event_type=EVENT_USER_SIGNED_IN,
        entity_type=ENTITY_USER,
        entity_id=user.id,
        payload={"role": user.role},
    )
    await db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
