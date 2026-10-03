"""
Named permission groups (app/api/dependencies/permissions.py) match
docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md exactly -- this test is the thing that
would fail if the two ever drift apart.
"""

from app.api.dependencies.permissions import require_approve, require_configure, require_operate
from app.models.user import UserRole


class _FakeUser:
    def __init__(self, role):
        self.role = role


async def _allowed(dependency, role) -> bool:
    from fastapi import HTTPException

    try:
        await dependency(current_user=_FakeUser(role))
        return True
    except HTTPException:
        return False


async def test_configure_matches_the_proposed_matrix():
    for role in (UserRole.ADMIN, UserRole.REGULATORY_MANAGER, UserRole.COMPLIANCE_MANAGER):
        assert await _allowed(require_configure, role), role
    for role in (UserRole.REVIEWER, UserRole.ANALYST, UserRole.VIEWER):
        assert not await _allowed(require_configure, role), role


async def test_operate_matches_the_proposed_matrix():
    for role in (
        UserRole.ADMIN,
        UserRole.REGULATORY_MANAGER,
        UserRole.COMPLIANCE_MANAGER,
        UserRole.REVIEWER,
    ):
        assert await _allowed(require_operate, role), role
    for role in (UserRole.ANALYST, UserRole.VIEWER):
        assert not await _allowed(require_operate, role), role


async def test_approve_matches_the_proposed_matrix():
    for role in (UserRole.ADMIN, UserRole.COMPLIANCE_MANAGER, UserRole.REVIEWER):
        assert await _allowed(require_approve, role), role
    for role in (UserRole.REGULATORY_MANAGER, UserRole.ANALYST, UserRole.VIEWER):
        assert not await _allowed(require_approve, role), role
