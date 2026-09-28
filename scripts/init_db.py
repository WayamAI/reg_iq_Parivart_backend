"""
Database initialisation and seeding.

    python -m scripts.init_db              # create tables, add missing columns, seed
    python -m scripts.init_db --no-seed    # schema only
    python -m scripts.init_db --check      # report drift, change nothing

This exists because the project has no Alembic environment yet (`alembic` is in
requirements.txt but there is no alembic.ini or versions/ directory), so the schema has
been applied ad hoc. That is how the live database ended up missing tables and columns that
the models had already grown.

Scope and limits -- read before relying on this:

  * `create_all` adds missing TABLES. It never alters an existing one.
  * `sync_columns` adds missing nullable COLUMNS. It is additive only.
  * It will NOT drop columns, change types, rename anything, add constraints to existing
    tables, or backfill data.

It is a stopgap for development, not a migration tool. Anything beyond an additive column
needs a real Alembic migration.
"""

import argparse
import asyncio
import sys
from typing import Dict, List, Tuple

from sqlalchemy import text

from app.db.base import Base
from app.db.database import AsyncSessionLocal, engine

# Importing the package registers every model with Base.metadata.
import app.models  # noqa: F401
from app.seeds.demo_data import seed_demo_data


async def _existing_schema(conn) -> Dict[str, set]:
    """{table_name: {column_name, ...}} for the connected database."""
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = (
            await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        ).scalars().all()
        schema = {}
        for table in rows:
            cols = await conn.execute(text(f'PRAGMA table_info("{table}")'))
            schema[table] = {row[1] for row in cols}
        return schema

    rows = await conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
    )
    schema: Dict[str, set] = {}
    for table_name, column_name in rows:
        schema.setdefault(table_name, set()).add(column_name)
    return schema


def _missing(existing: Dict[str, set]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return (missing tables, missing (table, column) pairs) against the models."""
    missing_tables, missing_columns = [], []
    for name, table in Base.metadata.tables.items():
        if name not in existing:
            missing_tables.append(name)
            continue
        for column in table.columns:
            if column.name not in existing[name]:
                missing_columns.append((name, column.name))
    return missing_tables, missing_columns


async def sync_columns(conn, missing_columns) -> List[str]:
    """Add missing columns. Additive only, and refuses anything NOT NULL without a default."""
    applied = []
    for table_name, column_name in missing_columns:
        column = Base.metadata.tables[table_name].columns[column_name]
        if not column.nullable and column.server_default is None and column.default is None:
            print(
                f"  SKIP {table_name}.{column_name}: NOT NULL without a default cannot be "
                f"added to a populated table safely -- needs a real migration.",
                file=sys.stderr,
            )
            continue
        ddl_type = column.type.compile(dialect=conn.dialect)
        await conn.execute(
            text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl_type}')
        )
        applied.append(f"{table_name}.{column_name}")
    return applied


async def main(seed: bool, check_only: bool) -> int:
    async with engine.begin() as conn:
        existing = await _existing_schema(conn)
        missing_tables, missing_columns = _missing(existing)

        if check_only:
            print(f"database : {engine.url.render_as_string(hide_password=True)}")
            print(f"tables   : {len(existing)} present, {len(Base.metadata.tables)} expected")
            print(f"missing tables : {missing_tables or 'none'}")
            print(
                "missing columns:",
                [f"{t}.{c}" for t, c in missing_columns] or "none",
            )
            return 1 if (missing_tables or missing_columns) else 0

        if missing_tables:
            print(f"creating {len(missing_tables)} table(s): {', '.join(missing_tables)}")
        await conn.run_sync(Base.metadata.create_all)

        if missing_columns:
            print(f"adding {len(missing_columns)} column(s)")
            for applied in await sync_columns(conn, missing_columns):
                print(f"  + {applied}")

        if not missing_tables and not missing_columns:
            print("schema already up to date")

    if seed:
        async with AsyncSessionLocal() as session:
            org = await seed_demo_data(session)
            print(f"seed: {org.name} ({org.id})")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-seed", action="store_true", help="schema only, do not seed")
    parser.add_argument(
        "--check", action="store_true", help="report drift and exit non-zero if any"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(seed=not args.no_seed, check_only=args.check)))
