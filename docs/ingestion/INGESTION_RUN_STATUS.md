# Regulatory Source Ingestion-Run: Current Implementation Status

Date: 2026-10-03 (updated same day). Method: direct source inspection of `app/api/routers/regulatory_sources.py` and a repository-wide `grep` for `process_source_run` (zero matches outside the original commented-out call site, now removed — see Update below).

**Update**: step 1 of the follow-up plan below (originally "recommended, not implemented") has since been implemented in this session, in its own commit (`fix(regulatory): report ingestion runs as FAILED instead of eternally QUEUED`). The sections below describing "currently QUEUED forever" describe the state *before* that fix; the corrected current behavior is summarized first.

## Current behavior (as of the fix above)

`POST /sources/{id}/run` still creates exactly one `IngestionRun` row, but now with `status=IngestionStatus.FAILED`, `completed_at` set, and an explicit `error` message naming the source's `source_type` (e.g. `"No ingestion adapter is implemented for source_type=RSS. This source's run was recorded but could not be executed."`). No document is fetched — this is **not** new ingestion capability, only an honest status for a run that cannot proceed. `FAILED` is a state the frontend already renders distinctly and stops polling on immediately (`TERMINAL_INGESTION_STATES` in the sibling frontend repo's `src/services/api/types.ts`), so a user triggering a run now gets an immediate, clear "did not work" signal instead of an indefinite "queued" that never resolves. `RegulatorySource.last_run_at`/`last_success_at`/`last_error` are still not updated — see the follow-up plan, item 2 onward, which remains entirely unimplemented.

## API endpoint and request schema

`POST /api/v1/regulatory/sources/{source_id}/run` — no request body. Requires a valid JWT (any authenticated, active user of any organization; sources are global, not tenant-scoped — see below). Response: `IngestionRunResponse` (the created `IngestionRun` row), HTTP `202 Accepted`. `404` if the source doesn't exist, `400` if the source is `enabled=False`.

## What is currently persisted

Exactly one row: a new `IngestionRun` with `id`, `source_id`, `status=IngestionStatus.FAILED`, `completed_at`, and `error` (as of the fix above — previously `status=IngestionStatus.QUEUED` with `error` left `None`). `started_at`/`documents_discovered`/`documents_downloaded`/`documents_processed`/`documents_failed` are left at their column defaults (`None`/`0`) either way — no document is actually fetched. Nothing on the parent `RegulatorySource` (`last_run_at`, `last_success_at`, `last_error`) is ever updated by this endpoint.

## Whether an adapter is invoked

**No.** `RegulatorySource.source_type`/`connector_type` (`RSS`, `API`, `WEB_SERVICE`, `HTML`, `DOCUMENT`) are stored classifications with no corresponding adapter class or dispatch logic anywhere in the codebase. Confirmed by `grep` across `app/` for any module implementing RSS parsing, HTML scraping, or an external API client tied to these enum values — none exists.

## Whether a job or processing function actually runs

**No.** The commented-out line that would have started one has been removed as part of the honesty fix above (it referenced `process_source_run`, which does not exist anywhere in the codebase — not a disabled-but-present function, it was never written). The endpoint's `background_tasks: BackgroundTasks` parameter is now genuinely unused and could be removed in a future cleanup; it is left in place here to keep this change scoped to the status-honesty fix.

## How status and errors are represented

`IngestionRun.status` is now set directly to `FAILED` at creation, with `completed_at` and a descriptive `error` populated in the same insert (as of the fix above). It can never reach `RUNNING`, `COMPLETED`, or `PARTIAL` through this endpoint, because nothing fetches or processes anything — there is no adapter to succeed or partially succeed. `GET /sources/{id}/runs` and `GET /sources/runs/{run_id}` show this `FAILED` status and `error` immediately; no polling is needed and the frontend's own terminal-state handling stops immediately rather than exhausting `MAX_POLLS`.

## Source adapters: implemented vs. placeholder

| Adapter | Status |
|---|---|
| RSS (`SourceType.RSS`) | Not implemented — no code |
| HTML (`SourceType.HTML`) | Not implemented — no code |
| API / WEB_SERVICE | Not implemented — no code |
| DOCUMENT (manual upload) | **Implemented, but via a completely separate code path** — `POST /regulatory/documents/upload`, not this endpoint. The "Manual Upload Source" row the demo seed creates (`app/seeds/demo_data.py`) exists as a `RegulatorySource` record for labeling/grouping purposes only; uploading a document does not go through `run_source` at all. |

## What the frontend can currently observe

- Calling `POST /sources/{id}/run` returns `202` with the `IngestionRun` already at `status: "FAILED"` and a populated `error` naming the missing adapter by `source_type`.
- `GET /sources/{id}/runs` and `GET /sources/runs/{run_id}` show the same settled `FAILED` status immediately — no polling delay, no indefinite "queued" state.
- No document is ever created by this endpoint, for any source, regardless of `source_type` — that part is unchanged. The difference is that the API now says so immediately and explicitly, instead of implying work is still in progress.

## Follow-up plan

1. ~~**Immediate, small, safe step**: ...~~ **Done this session** (option (b): `IngestionRun.status = FAILED` immediately with an explicit `error`). Verified by `app/tests/test_regulatory_sources_api.py` (6 tests): the response and a subsequent `GET /sources/runs/{run_id}` both show `FAILED` with a populated `error`, `404`/`400` behavior for an unknown/disabled source is unchanged.
2. **Per-source-type adapter work** (not implemented), each its own scoped effort with its own tests:
   - DOCUMENT sources: no adapter needed (already handled by manual upload); the seeded "Manual Upload Source" row could be clarified in its own description/metadata to state it is never triggered via `run_source`.
   - RSS: smallest real adapter to build — fetch the feed, diff against previously-seen entries (idempotency key: entry GUID or link), create `RegulatoryDocument` rows for new entries only.
   - HTML: requires a per-source scraping strategy; higher risk of brittleness, should not be generalized into an unrestricted crawler (explicitly out of scope per this task's own instruction) — each HTML source needs its own targeted extraction rule, not a generic "fetch and guess" approach.
   - API/WEB_SERVICE: needs a per-source request/response mapping; no generic implementation is safe to write without knowing the specific regulator API's shape.
3. **Idempotency**: any real adapter must be safe to run twice without creating duplicate `RegulatoryDocument` rows — the per-organization `sha256` dedup fixed this session (see `docs/engineering-audit/` and the `0004_tenant_scoped_doc_dedup` migration) is the right primitive to build on, since a re-fetched, unchanged document will hash identically.
4. **Error reporting**: a real adapter must set `IngestionRun.status = FAILED` with a populated `error` field on any fetch/parse failure, and must update `RegulatorySource.last_run_at`/`last_success_at`/`last_error` — none of which exists today because nothing transitions the run at all.
5. **Tests required before any of the above is claimed done**: a successful run creates the expected `RegulatoryDocument` row(s); a re-run with no new content creates zero new rows (idempotency); a fetch failure sets `FAILED` with a populated `error` and does not leave the run at `QUEUED` forever; a disabled source is rejected before any network call is attempted (already true today, via the `400` check, and must remain true).

No document-fetching ingestion behavior was implemented or is claimed to work in this session. `run_source` persists a request record and an honest failure reason — nothing more. Steps 2–5 above remain entirely unimplemented.
