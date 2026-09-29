"""phase 7 review and action fields

Brings the actions and impact_reviews tables up to the Phase 7 model:

  * actions gains priority and completed_at, and status becomes NOT NULL.
  * impact_reviews gains organization_id (so review queries can be tenant-scoped
    without a join), new_state, previous_state and updated_at.
  * The decision column widens to carry the renamed ReviewDecision values.

Written to be safe on a populated database. Every new NOT NULL column is added
nullable, backfilled, and only then constrained; the renamed enum values are mapped
across rather than left to fail a later read. The columns are declared with
native_enum=False, so they are plain VARCHAR here and the enumeration is enforced in
the application layer -- there is no PostgreSQL ENUM type to create or drop.

Revision ID: 0002_phase7
Revises: 0001_baseline
Create Date: 2026-09-29 17:05:29.493989

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002_phase7'
down_revision: Union[str, None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Named explicitly so downgrade() can drop it. An unnamed constraint cannot be
# dropped by a later revision.
FK_REVIEW_ORG = "fk_impact_reviews_organization_id_organizations"

ACTION_PRIORITY = sa.Enum(
    "LOW", "MEDIUM", "HIGH", name="actionpriority", native_enum=False
)
REVIEW_DECISION = sa.Enum(
    "ACCEPT",
    "MODIFY",
    "REJECT",
    "NEEDS_MORE_INFORMATION",
    name="reviewdecision",
    native_enum=False,
)


def upgrade() -> None:
    # --- actions ----------------------------------------------------------------------
    # Added with a server default so existing rows get a value, then the default is
    # dropped: the model supplies MEDIUM application-side and a lingering server default
    # would show up as drift on the next autogenerate.
    op.add_column(
        "actions",
        sa.Column("priority", ACTION_PRIORITY, nullable=False, server_default="MEDIUM"),
    )
    op.alter_column("actions", "priority", server_default=None)

    op.add_column(
        "actions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # ActionStatus.DONE was renamed to COMPLETED. Map any existing rows before the
    # column is constrained, so no row is left holding a value the model rejects.
    op.execute("UPDATE actions SET status = 'COMPLETED' WHERE status = 'DONE'")
    op.execute("UPDATE actions SET status = 'OPEN' WHERE status IS NULL")
    op.alter_column(
        "actions", "status", existing_type=sa.VARCHAR(length=11), nullable=False
    )

    # --- impact_reviews ---------------------------------------------------------------
    op.add_column(
        "impact_reviews", sa.Column("previous_state", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "impact_reviews", sa.Column("new_state", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "impact_reviews",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Widen before rewriting values: NEEDS_MORE_INFORMATION is 22 characters and would
    # not fit the previous VARCHAR(10).
    op.alter_column(
        "impact_reviews",
        "decision",
        existing_type=sa.VARCHAR(length=10),
        type_=REVIEW_DECISION,
        existing_nullable=False,
    )
    op.execute("UPDATE impact_reviews SET decision = 'ACCEPT' WHERE decision = 'ACCEPTED'")
    op.execute("UPDATE impact_reviews SET decision = 'REJECT' WHERE decision = 'REJECTED'")
    op.execute(
        "UPDATE impact_reviews SET decision = 'NEEDS_MORE_INFORMATION' "
        "WHERE decision = 'NEEDS_INFO'"
    )

    # organization_id is denormalised from the parent assessment. Add it nullable,
    # backfill from that parent, then constrain -- a straight NOT NULL add would fail on
    # any database that already holds reviews.
    op.add_column(
        "impact_reviews",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        """
        UPDATE impact_reviews AS r
           SET organization_id = a.organization_id
          FROM impact_assessments AS a
         WHERE a.id = r.impact_assessment_id
        """
    )
    # A review whose assessment has vanished has no tenant and cannot be made valid.
    op.execute("DELETE FROM impact_reviews WHERE organization_id IS NULL")
    op.alter_column(
        "impact_reviews",
        "organization_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.create_index(
        op.f("ix_impact_reviews_organization_id"),
        "impact_reviews",
        ["organization_id"],
        unique=False,
    )
    op.create_foreign_key(
        FK_REVIEW_ORG, "impact_reviews", "organizations", ["organization_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(FK_REVIEW_ORG, "impact_reviews", type_="foreignkey")
    op.drop_index(
        op.f("ix_impact_reviews_organization_id"), table_name="impact_reviews"
    )
    op.drop_column("impact_reviews", "organization_id")

    # Map back before narrowing, or the longest value would be truncated.
    op.execute("UPDATE impact_reviews SET decision = 'ACCEPTED' WHERE decision = 'ACCEPT'")
    op.execute("UPDATE impact_reviews SET decision = 'REJECTED' WHERE decision = 'REJECT'")
    op.execute(
        "UPDATE impact_reviews SET decision = 'NEEDS_INFO' "
        "WHERE decision = 'NEEDS_MORE_INFORMATION'"
    )
    # MODIFY has no pre-Phase-7 equivalent; it maps onto the closest older value.
    op.execute("UPDATE impact_reviews SET decision = 'ACCEPTED' WHERE decision = 'MODIFY'")
    op.alter_column(
        "impact_reviews",
        "decision",
        existing_type=REVIEW_DECISION,
        type_=sa.VARCHAR(length=10),
        existing_nullable=False,
    )

    op.drop_column("impact_reviews", "updated_at")
    op.drop_column("impact_reviews", "new_state")
    op.drop_column("impact_reviews", "previous_state")

    op.alter_column(
        "actions", "status", existing_type=sa.VARCHAR(length=11), nullable=True
    )
    op.execute("UPDATE actions SET status = 'DONE' WHERE status = 'COMPLETED'")
    op.drop_column("actions", "completed_at")
    op.drop_column("actions", "priority")
