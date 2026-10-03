from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        # Deactivating a user must take effect immediately. Without this, an access token
        # issued before deactivation stays usable until it expires.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed: UserRole):
    """
    Dependency factory: only the given roles may reach the endpoint.

    Fail-closed by construction: `current_user.role` must be a member of `allowed`,
    checked by membership in an explicit set, so a role that is not listed -- including
    any value added to UserRole later that this call site hasn't been updated for --
    is denied, never allowed by default. See docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md
    for the matrix this is built from.

    Deliberately separate from tenant scoping: this only answers "is this role allowed
    to attempt this *kind* of operation at all". Every router must still filter by
    `current_user.organization_id` itself -- a role check here does not and must not
    grant cross-tenant access, including for ADMIN.
    """
    allowed_set = set(allowed)

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _check
