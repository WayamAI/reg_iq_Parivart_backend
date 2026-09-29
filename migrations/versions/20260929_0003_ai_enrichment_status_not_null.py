"""make impact_assessments.ai_enrichment_status NOT NULL

Corrects real drift between the models and an already-deployed database.

ImpactAssessment declares ai_enrichment_status as nullable=False, because every
assessment is meant to state the outcome of the optional AI pass -- DISABLED when
enrichment is switched off, and the specific failure otherwise. The column reached the
deployed database through an ad-hoc script rather than a migration, and that script
added it nullable. A database built from revision 0001 already has it NOT NULL, so this
revision is a no-op there and a correction on the older one.

Existing NULLs are backfilled to DISABLED: a row with no recorded outcome predates
enrichment being attempted, which is exactly what DISABLED means.

Revision ID: 0003_enrichment_not_null
Revises: 0002_phase7
Create Date: 2026-09-29 17:06:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003_enrichment_not_null'
down_revision: Union[str, None] = '0002_phase7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE impact_assessments SET ai_enrichment_status = 'DISABLED' "
        "WHERE ai_enrichment_status IS NULL"
    )
    op.alter_column(
        "impact_assessments",
        "ai_enrichment_status",
        existing_type=sa.VARCHAR(length=16),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "impact_assessments",
        "ai_enrichment_status",
        existing_type=sa.VARCHAR(length=16),
        nullable=True,
    )
