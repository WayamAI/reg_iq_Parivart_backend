"""scope regulatory_documents.sha256 uniqueness to organization_id

The sha256 column was globally unique (ix_regulatory_documents_sha256, unique=True), so a
second organization uploading byte-identical content (e.g. a public regulatory PDF) either
failed the insert outright, or -- as the application's own duplicate-check path turned out
to do -- was silently handed back the FIRST organization's document id as "your duplicate"
without ever creating its own record. That is a cross-tenant existence/identity leak as
well as a functional bug: a real upload for the second organization never happened.

This migration replaces the global unique index with:
  - a composite UNIQUE(organization_id, sha256) constraint, matching the corrected
    application-level dedup check (app/services/document_service.check_duplicate_sha256),
  - a plain (non-unique) index on sha256 alone, preserved for lookup performance.

Safety: because the OLD constraint was already a global unique index, no two existing rows
can already share a sha256 value, so the new composite constraint cannot conflict with any
existing data -- it is strictly less restrictive than what was already enforced. The
upgrade step still runs an explicit pre-check query and aborts rather than guessing if that
invariant is ever found to be violated, since this migration must never delete or reassign
existing document records to force a constraint through.

Revision ID: 0004_tenant_scoped_doc_dedup
Revises: 0003_enrichment_not_null
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004_tenant_scoped_doc_dedup'
down_revision: Union[str, None] = '0003_enrichment_not_null'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Defensive check only -- see module docstring for why this cannot actually fire
    # against data that has been under the old global-unique constraint. If it ever
    # does fire, that indicates the old constraint was bypassed (e.g. by a bulk load
    # that skipped the ORM), and this migration refuses to silently paper over it by
    # deleting or reassigning anyone's records.
    duplicates = conn.execute(
        sa.text(
            "SELECT organization_id, sha256, COUNT(*) AS c "
            "FROM regulatory_documents "
            "WHERE sha256 IS NOT NULL "
            "GROUP BY organization_id, sha256 "
            "HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "Refusing to add UNIQUE(organization_id, sha256): "
            f"{len(duplicates)} (organization_id, sha256) pair(s) already have more than "
            "one regulatory_documents row. Resolve these manually -- this migration will "
            "not delete or reassign any existing document record automatically."
        )

    op.drop_index(op.f('ix_regulatory_documents_sha256'), table_name='regulatory_documents')
    op.create_index(
        op.f('ix_regulatory_documents_sha256'), 'regulatory_documents', ['sha256'], unique=False
    )
    op.create_unique_constraint(
        'uq_regulatory_documents_org_sha256',
        'regulatory_documents',
        ['organization_id', 'sha256'],
    )


def downgrade() -> None:
    # No pre-check here, deliberately: if any (organization_id, sha256) pair now has more
    # than one row -- the exact, expected outcome of this migration doing its job -- the
    # database itself refuses to recreate the old global-unique index
    # (UniqueViolationError on CREATE UNIQUE INDEX) and the whole downgrade transaction
    # rolls back. Verified directly against a real PostgreSQL 14 instance: inserting two
    # organizations' documents with the same sha256, then downgrading, fails loudly with
    # that exact error and leaves the schema at 0004 -- it never silently deletes or
    # reassigns a row to force the old constraint through.
    op.drop_constraint(
        'uq_regulatory_documents_org_sha256', 'regulatory_documents', type_='unique'
    )
    op.drop_index(op.f('ix_regulatory_documents_sha256'), table_name='regulatory_documents')
    op.create_index(
        op.f('ix_regulatory_documents_sha256'), 'regulatory_documents', ['sha256'], unique=True
    )
