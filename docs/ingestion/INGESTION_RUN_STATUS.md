# Regulatory Source Ingestion-Run: Current Implementation Status

Date: 2026-10-03. Method: direct source inspection of `app/api/routers/regulatory_sources.py` and a repository-wide `grep` for `process_source_run` (zero matches outside the commented-out call site itself).

## API endpoint and request schema

`POST /api/v1/regulatory/sources/{source_id}/run` — no request body. Requires a valid JWT (any authenticated, active user of any organization; sources are global, not tenant-scoped — see below). Response: `IngestionRunResponse` (the created `IngestionRun` row), HTTP `202 Accepted`. `404` if the source doesn't exist, `400` if the source is `enabled=False`.

## What is currently persisted

Exactly one row: a new `IngestionRun` with `id`, `source_id`, `status=IngestionStatus.QUEUED`. `started_at`/`documents_discovered`/`documents_downloaded`/`documents_processed`/`documents_failed`/`error` are left at their column defaults (`None`/`0`). Nothing on the parent `RegulatorySource` (`last_run_at`, `last_success_at`, `last_error`) is ever updated by this endpoint.

## Whether an adapter is invoked

**No.** `RegulatorySource.source_type`/`connector_type` (`RSS`, `API`, `WEB_SERVICE`, `HTML`, `DOCUMENT`) are stored classifications with no corresponding adapter class or dispatch logic anywhere in the codebase. Confirmed by `grep` across `app/` for any module implementing RSS parsing, HTML scraping, or an external API client tied to these enum values — none exists.

## Whether a job or processing function actually runs

**No.** The exact line that would start one is present in source but deliberately commented out:
```python
# In the future, we would add a background task to process the source
# For now, we just return the run and the client can poll for status
# background_tasks.add_task(process_source_run, run_id, source_id, db)
```
`process_source_run` does not exist anywhere in the codebase — this is not a disabled-but-present function, it was never written. The endpoint signature already accepts `background_tasks: BackgroundTasks` as an unused parameter, left in place from when this was scaffolded.

## How status and errors are represented

`IngestionRun.status` only ever takes the value it is given at creation (`QUEUED`) in the current code path — it can never reach `RUNNING`, `COMPLETED`, `PARTIAL`, or `FAILED` through this endpoint, because nothing transitions it after the initial insert. `GET /sources/{id}/runs` and `GET /sources/runs/{run_id}` will therefore always show every run frozen at `QUEUED` indefinitely.

## Source adapters: implemented vs. placeholder

| Adapter | Status |
|---|---|
| RSS (`SourceType.RSS`) | Not implemented — no code |
| HTML (`SourceType.HTML`) | Not implemented — no code |
| API / WEB_SERVICE | Not implemented — no code |
| DOCUMENT (manual upload) | **Implemented, but via a completely separate code path** — `POST /regulatory/documents/upload`, not this endpoint. The "Manual Upload Source" row the demo seed creates (`app/seeds/demo_data.py`) exists as a `RegulatorySource` record for labeling/grouping purposes only; uploading a document does not go through `run_source` at all. |

## What the frontend can currently observe

- Calling `POST /sources/{id}/run` succeeds (`202`) and returns a real `IngestionRun` id.
- Polling `GET /sources/{id}/runs` or `GET /sources/runs/{run_id}` will show that run permanently at `QUEUED` — there is no event, timeout, or status change to observe, ever, for any source, regardless of `source_type`.
- No document is created, no error is ever surfaced, and no distinction exists yet between "not implemented" and "queued and legitimately waiting" from the API's perspective. **This is the central honesty problem**: the response looks identical to a real asynchronous job that simply hasn't finished yet.

## Recommended follow-up plan (not implemented this session — scope and risk too large for an isolated commit)

1. **Immediate, small, safe step**: change the `202`/`QUEUED` response to something that does not imply forward progress — e.g. keep the `IngestionRun` row (useful as an audit record of "someone asked for this source to be run") but either (a) return `501 Not Implemented` for source types with no adapter, or (b) set `IngestionRun.status = FAILED` immediately with `error = "No adapter implemented for source_type=<type>"`. Either is a one-file change with a direct, fast test (assert the endpoint no longer claims success for an unimplemented source type).
2. **Per-source-type adapter work**, each its own scoped effort with its own tests:
   - DOCUMENT sources: no adapter needed (already handled by manual upload); the seeded "Manual Upload Source" row could be clarified in its own description/metadata to state it is never triggered via `run_source`.
   - RSS: smallest real adapter to build — fetch the feed, diff against previously-seen entries (idempotency key: entry GUID or link), create `RegulatoryDocument` rows for new entries only.
   - HTML: requires a per-source scraping strategy; higher risk of brittleness, should not be generalized into an unrestricted crawler (explicitly out of scope per this task's own instruction) — each HTML source needs its own targeted extraction rule, not a generic "fetch and guess" approach.
   - API/WEB_SERVICE: needs a per-source request/response mapping; no generic implementation is safe to write without knowing the specific regulator API's shape.
3. **Idempotency**: any real adapter must be safe to run twice without creating duplicate `RegulatoryDocument` rows — the per-organization `sha256` dedup fixed this session (see `docs/engineering-audit/` and the `0004_tenant_scoped_doc_dedup` migration) is the right primitive to build on, since a re-fetched, unchanged document will hash identically.
4. **Error reporting**: a real adapter must set `IngestionRun.status = FAILED` with a populated `error` field on any fetch/parse failure, and must update `RegulatorySource.last_run_at`/`last_success_at`/`last_error` — none of which exists today because nothing transitions the run at all.
5. **Tests required before any of the above is claimed done**: a successful run creates the expected `RegulatoryDocument` row(s); a re-run with no new content creates zero new rows (idempotency); a fetch failure sets `FAILED` with a populated `error` and does not leave the run at `QUEUED` forever; a disabled source is rejected before any network call is attempted (already true today, via the `400` check, and must remain true).

No ingestion behavior was implemented or claimed as fetched in this session. This document itself is the honest status: `run_source` persists a request record and nothing else.
