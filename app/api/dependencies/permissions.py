"""
Named permission dependencies, built on require_role().

Centralizes the role sets from docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md in one
place so every router applies the same groups rather than re-deriving them, and so the
matrix doc and the enforced code can be diffed against each other directly.

ANALYST is deliberately excluded from every write permission here, per the matrix
proposal's resolution of its one open policy question: the stricter, safer default
(read-only) is enforced now, with loosening it later being a backward-compatible,
single-line change if that policy call is made differently.
"""

from app.api.dependencies.auth import require_role
from app.models.user import UserRole

# Manage portfolio structure, regulatory sources/authorities, trigger ingestion, and
# upload/process documents. ANALYST excluded -- see module docstring.
require_configure = require_role(
    UserRole.ADMIN, UserRole.REGULATORY_MANAGER, UserRole.COMPLIANCE_MANAGER
)

# Create/transition remediation actions, upload evidence.
require_operate = require_role(
    UserRole.ADMIN,
    UserRole.REGULATORY_MANAGER,
    UserRole.COMPLIANCE_MANAGER,
    UserRole.REVIEWER,
)

# File a human review decision -- the product's explicit judgment gate.
require_approve = require_role(
    UserRole.ADMIN, UserRole.COMPLIANCE_MANAGER, UserRole.REVIEWER
)
