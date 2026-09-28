#!/usr/bin/env python3
"""
Migration script to add ai_enrichment_status column to impact_assessments table.
This addresses the frontend-reported issue where the column was missing from the database.
"""

import asyncio
from sqlalchemy import text
from app.db.database import engine

async def upgrade():
    """Add the ai_enrichment_status column to impact_assessments table."""
    async with engine.begin() as conn:
        # First, check if the column already exists
        result = await conn.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'impact_assessments'
                AND column_name = 'ai_enrichment_status'
            """)
        )
        column_exists = result.scalar() is not None

        if column_exists:
            print("Column ai_enrichment_status already exists in impact_assessments table")
            return

        # Add the column with default value
        print("Adding ai_enrichment_status column to impact_assessments table...")
        await conn.execute(
            text("""
                ALTER TABLE impact_assessments
                ADD COLUMN ai_enrichment_status VARCHAR(20)
                NOT NULL DEFAULT 'DISABLED'
            """)
        )

        # Create the enum type if it doesn't exist (PostgreSQL)
        # Note: For simplicity, we're using VARCHAR with constraint check
        # In a production environment with proper Alembic, we would create a proper ENUM type
        print("Added ai_enrichment_status column with DEFAULT 'DISABLED'")

        # Update any existing NULL values to DEFAULT (though NOT NULL should prevent this)
        await conn.execute(
            text("""
                UPDATE impact_assessments
                SET ai_enrichment_status = 'DISABLED'
                WHERE ai_enrichment_status IS NULL
            """)
        )

        print("Migration completed successfully!")

async def downgrade():
    """Remove the ai_enrichment_status column from impact_assessments table."""
    async with engine.begin() as conn:
        # Check if column exists before trying to drop it
        result = await conn.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'impact_assessments'
                AND column_name = 'ai_enrichment_status'
            """)
        )
        column_exists = result.scalar() is not None

        if not column_exists:
            print("Column ai_enrichment_status does not exist in impact_assessments table")
            return

        print("Removing ai_enrichment_status column from impact_assessments table...")
        await conn.execute(
            text("ALTER TABLE impact_assessments DROP COLUMN ai_enrichment_status")
        )
        print("Migration rolled back successfully!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "downgrade":
        asyncio.run(downgrade())
    else:
        asyncio.run(upgrade())