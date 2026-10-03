# Database Migration Status

Date: 2026-10-03. This records the actual, verified state — not an assumption from a prior session's report, and not a claim based only on `alembic history`.

## Target database identification

Before checking anything, the actual configured target was identified from the backend's own `.env` (value redacted, host/db name only, since this is the project's own development configuration, not a shared or unknown system):

```
DATABASE_URL=postgresql+asyncpg://<redacted>@localhost:5432/parivart
```

This is the local PostgreSQL 14 instance already running on this machine (`brew services list` showed `postgresql@14` started). `parivart` is a local development database on `localhost`, owned by the local user, not a shared, staging, or production system. Two other locally-visible databases (`parivart_acceptance`, `parivart_migcheck`) were explicitly **not** touched, since their ownership/purpose relative to this session's work was not established — only the database the app's own `.env` actually points at was inspected.

## Current migration version — confirmed by direct query

```sql
SELECT version_num FROM alembic_version;
-- 0004_tenant_scoped_doc_dedup
```

**Migration `0004_tenant_scoped_doc_dedup` is applied** to the `parivart` development database. This was re-confirmed again in this session via a direct `psql` query against `alembic_version`, not inferred from the migration file or from a prior session's claim.

## Schema confirmed to match the migration (not just the version stamp)

```
\d regulatory_documents
 ...
 "ix_regulatory_documents_sha256" btree (sha256)
 "uq_regulatory_documents_org_sha256" UNIQUE CONSTRAINT, btree (organization_id, sha256)
```

The actual DDL matches what migration `0004` should have produced: a plain (non-unique) index on `sha256`, plus a composite `UNIQUE(organization_id, sha256)` constraint — not merely a version-table stamp with no corresponding schema change (which could happen if someone had run `alembic stamp` without `upgrade`).

## Data integrity check

```sql
SELECT organization_id, sha256, count(*) FROM regulatory_documents
WHERE sha256 IS NOT NULL GROUP BY organization_id, sha256 HAVING count(*) > 1;
-- 0 rows
```

No `(organization_id, sha256)` pair has more than one row — the composite constraint this migration adds is satisfied by the actual data, not merely declared. `SELECT count(*) FROM regulatory_documents` returned `3` total documents in this database at the time of this check.

## How this migration came to be applied

**Not executed by this agent session.** Earlier work this session authored migration `0004` and verified it only via `alembic history` (chain resolution) and against a disposable, uniquely-named scratch database (`parivart_migration_verify_<timestamp>`, created and dropped within that session) — explicitly *not* applied to `parivart` at that time, per the instruction not to run a migration against an unconfirmed target. By the time of this session's inspection, `parivart`'s `alembic_version` already read `0004_tenant_scoped_doc_dedup` with the matching schema in place. The most likely explanation is that the project owner (or another process with access to this machine) ran `alembic upgrade head` against their own local development database between sessions — a normal, expected development action. This session did not run `alembic upgrade`, `alembic stamp`, or any other migration command against `parivart`; it only read from it (`SELECT`, `\d`), which it is always safe to do.

## Locking, downtime, and rollback — assessed for completeness, now moot for this target

These were assessed before confirming `0004`'s actual state:
- The migration's own `upgrade()` performs `DROP INDEX` / `CREATE INDEX` / `ADD CONSTRAINT` — on a table with only 3 rows (confirmed above), this is effectively instantaneous; lock duration is not a practical concern at this data volume.
- `downgrade()` was verified (in the earlier scratch-database session) to fail loudly, not silently destroy data, if a genuine cross-tenant duplicate exists — see the migration file's own docstring and `docs/engineering-audit/` for that verification's detail.
- No backup was taken specifically for this check, since no write operation was performed against `parivart` in this session.

## Current status summary

| Question | Answer |
|---|---|
| Is `0004` applied to the intended development database? | **Yes — confirmed by direct query this session.** |
| Was it applied by this session? | No — found already applied; this session only read the database to confirm. |
| Does the live schema match what the migration should produce? | Yes — composite constraint confirmed present via `\d`. |
| Does existing data satisfy the new constraint? | Yes — zero violating `(organization_id, sha256)` pairs. |
| Was any destructive operation run against `parivart` this session? | No — read-only (`SELECT`, `\d`) only. |
