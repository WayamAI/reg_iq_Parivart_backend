"""
require_role(): the shared authorization dependency, tested in isolation before any
router is wired to it.
"""

import pytest
from fastapi import HTTPException

from app.api.dependencies.auth import require_role
from app.models.user import UserRole


class _FakeUser:
    def __init__(self, role):
        self.role = role


async def test_allowed_role_passes_through():
    check = require_role(UserRole.ADMIN, UserRole.REVIEWER)
    user = _FakeUser(UserRole.REVIEWER)

    result = await check(current_user=user)

    assert result is user


async def test_denied_role_raises_403():
    check = require_role(UserRole.ADMIN)
    user = _FakeUser(UserRole.VIEWER)

    with pytest.raises(HTTPException) as exc_info:
        await check(current_user=user)

    assert exc_info.value.status_code == 403


async def test_fails_closed_for_a_role_not_in_the_allowed_set_at_all():
    """A role that exists on UserRole but was never added to this call site's allowed
    set must still be denied -- the default is deny, not allow."""
    check = require_role(UserRole.ADMIN, UserRole.COMPLIANCE_MANAGER)

    for role in (UserRole.REGULATORY_MANAGER, UserRole.REVIEWER, UserRole.ANALYST, UserRole.VIEWER):
        with pytest.raises(HTTPException) as exc_info:
            await check(current_user=_FakeUser(role))
        assert exc_info.value.status_code == 403


async def test_empty_allowed_set_denies_everyone():
    check = require_role()
    with pytest.raises(HTTPException) as exc_info:
        await check(current_user=_FakeUser(UserRole.ADMIN))
    assert exc_info.value.status_code == 403
