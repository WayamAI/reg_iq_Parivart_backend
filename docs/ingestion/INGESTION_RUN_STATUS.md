# Regulatory Source Ingestion-Run: Current Implementation Status

Date: 2026-10-03, revised the same day after implementing a real RSS adapter. Earlier revisions of this document recorded first a stub (`QUEUED` forever) and then an honesty fix (`FAILED` immediately, no fetch). **Both are now superseded for `source_type=RSS`** — see below. Every other `source_type` still behaves per the honesty-fix section further down.

## Current behavior by source_type

| `source_type` | Behavior |
|---|---|
| `RSS` | **Real adapter.** Fetches the feed, parses entries, persists new ones as tenant-scoped `RegulatoryDocument` rows, returns accurate run counters. See "RSS adapter" below. |
| `DOCUMENT` | Not reachable via this endpoint at all — manual upload (`POST /regulatory/documents/upload`) is a separate code path. A `DOCUMENT`-type source triggered via `run_source` falls into the generic "no adapter" `FAILED` response below, same as `HTML`/`API`/`WEB_SERVICE`. |
| `HTML`, `API`, `WEB_SERVICE` | **Still a stub.** No adapter exists. `run_source` returns `202` with the `IngestionRun` already `FAILED` and an explicit `error` naming the `source_type` — honest, immediate, never an indefinite `QUEUED`. |

## RSS adapter

### Contract

- **Trigger**: `POST /api/v1/regulatory/sources/{id}/run` where the source's `source_type == RSS` and `enabled == True`. Requires `require_configure` (`ADMIN`/`REGULATORY_MANAGER`/`COMPLIANCE_MANAGER`).
- **Input**: `source.url` (the feed URL) and the triggering user's `organization_id`/`id` (for document ownership and audit attribution).
- **Tenant attribution (explicit design decision)**: `RegulatorySource`/`RegulatoryAuthority` are global, not tenant-scoped, and there is no subscription model deciding which organizations should receive a given source's content. This adapter attributes every document it creates to the *triggering user's organization* — exactly like a manual upload. Two different organizations independently running the same source each get their own document rows, enabled by the per-organization `sha256` dedup fixed earlier this session (migration `0004_tenant_scoped_doc_dedup`).
- **Output**: updates the `IngestionRun` row with a real `status` (`COMPLETED`/`PARTIAL`/`FAILED`), `completed_at`, `error` (on any failure), and `documents_discovered`/`documents_downloaded`/`documents_processed`/`documents_failed` counters. Also updates `RegulatorySource.last_run_at` (every run) and `last_success_at`/`last_error` (on success/failure respectively) — fields that existed on the model but were never written by any code path before this session.
- **Failure states**: `FAILED` if the fetch or parse of the whole feed fails, or if every individual entry fails to persist; `PARTIAL` if some entries persisted (created or duplicate) and others failed; `COMPLETED` if every entry succeeded or the feed had zero entries (an empty feed is a successful run that discovered nothing, not a failure).
- **Not implemented, deliberately**: fetching an entry's own link to pull a fuller article body, fetching enclosure/attachment URLs, or any generic crawling beyond the feed's own XML. Each entry's `title` + `description` *as given by the feed* becomes the document's `extracted_text` directly — there is no further extraction step, so the document is marked `PARSED`, never `ANALYZED` (no AI analysis ran).

### Implementation

| Module | Responsibility |
|---|---|
| `app/ingestion/url_safety.py` | SSRF-safe URL validation: only `http`/`https`, and every address a hostname resolves to must be a public, routable address (rejects loopback, private, link-local/cloud-metadata, multicast, reserved, unspecified). |
| `app/ingestion/rss_fetcher.py` | Safe retrieval: connect/read timeouts, a response size bound enforced *during* streaming download (not after buffering), manual redirect following with `url_safety` re-validation on every hop, bounded redirect count. |
| `app/ingestion/rss_parser.py` | Pure parsing (no network): RSS 2.0 and Atom, via `defusedxml` (guards against entity-expansion/"billion laughs" and external-entity attacks), bounded to `MAX_ENTRIES_PER_RUN` (50) regardless of feed size. |
| `app/ingestion/rss_ingestion.py` | Orchestrates fetch → parse → per-organization dedup → persist → run summary. Never raises — every failure mode becomes a `(status, error, counters)` result. |

### Safety protections verified by test

- SSRF: every blocked IP range (loopback, RFC 1918 private ranges, link-local/169.254.169.254, multicast, unspecified, IPv6 equivalents) individually rejected; a redirect target is re-validated, not just the original URL (`test_url_safety.py`, `test_rss_fetcher.py`).
- Response size bound enforced mid-stream, not after a server sends more than it declared (`test_rss_fetcher.py::test_oversized_response_is_rejected_during_download`).
- Entity-expansion bomb rejected, never expanded (`test_rss_parser.py::test_entity_expansion_bomb_is_rejected_not_expanded`).
- Malformed XML, missing titles/guids, unparseable dates all handled without crashing (`test_rss_parser.py`).

### Persistence and deduplication behavior

- Dedup key: `sha256(title + "\n\n" + description)`, checked per-organization via the existing `check_duplicate_sha256` — the same mechanism manual upload uses.
- Re-running the same source produces zero new documents for entries already ingested by that organization (`test_rss_ingestion.py::test_repeated_run_is_idempotent`, and over HTTP in `test_rss_source_run_api.py::test_running_the_same_rss_source_twice_does_not_duplicate`).
- Two organizations independently running the same source each get their own document row, not a shared one and not a cross-tenant collision (`test_rss_ingestion.py::test_two_organizations_ingesting_the_same_feed_each_get_their_own_documents`).
- A single bad entry (persistence failure) is caught and counted, not allowed to sink the whole run.

### Run-status accuracy

- A successful run: `COMPLETED`, `documents_discovered`/`documents_processed` matching the real counts, `error` is `None`.
- A fetch failure (network, timeout, non-2xx, unsafe URL): `FAILED`, all counters `0`, `error` populated with the real cause.
- An empty feed: `COMPLETED` with `documents_discovered == 0` — correctly distinguished from a failure.
- A source with no `url` configured: `FAILED` immediately, without attempting any network call.

### Test results

| File | Tests | Scope |
|---|---|---|
| `test_url_safety.py` | 17 | SSRF validation, fully mocked DNS resolver |
| `test_rss_fetcher.py` | 9 | Fetch behavior, fully mocked `httpx` transport |
| `test_rss_parser.py` | 7 | Feed parsing, fixture XML only |
| `test_rss_ingestion.py` | 6 | Orchestrator against the real DB/storage, `fetch_feed` monkeypatched |
| `test_rss_source_run_api.py` | 4 | End-to-end over HTTP (auth, role gating, persistence, counters), `fetch_feed` monkeypatched |

All run with **no real network access** — confirmed by construction (every test either mocks the transport/resolver or monkeypatches `fetch_feed` directly).

### Manual smoke-test procedure (not run as part of automated tests)

To verify against a real, trusted development feed by hand:

```bash
# 1. Register/login as a user with ADMIN/REGULATORY_MANAGER/COMPLIANCE_MANAGER role.
# 2. Create an authority and an RSS source pointing at a real, trusted feed URL, e.g.:
curl -X POST http://localhost:8000/api/v1/regulatory/sources/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"authority_id": "<id>", "name": "Smoke Test Feed", "source_type": "RSS", "connector_type": "RSS", "url": "<a real, trusted RSS feed URL you control or trust>", "enabled": true}'

# 3. Trigger a run and inspect the result:
curl -X POST http://localhost:8000/api/v1/regulatory/sources/<source_id>/run -H "Authorization: Bearer $TOKEN"

# 4. Confirm documents were created:
curl http://localhost:8000/api/v1/regulatory/documents/ -H "Authorization: Bearer $TOKEN"

# 5. Re-run and confirm documents_processed reflects duplicates, not new rows.
```

This was **not executed** as part of this session — no outbound network call to a real feed was made. The automated test suite above is what was actually run and passed.

## Known limitations

- Only RSS and Atom are supported; `HTML`/`API`/`WEB_SERVICE` remain an honest stub (see the per-source-type follow-up plan below).
- No scheduler exists — a run only happens when `POST /sources/{id}/run` is called; nothing triggers it automatically (and per this task's explicit instruction, nothing should automatically execute a registered source at application startup — confirmed not done).
- `MAX_ENTRIES_PER_RUN` (50) means a feed with more than 50 new items since the last run will only ingest the first 50 per call; a backlog larger than that requires multiple runs.
- Entry content is exactly what the feed provides (title + description) — no fetching of the entry's own article page, so a feed with only a teaser/summary yields a document with only that teaser/summary as its `extracted_text`.
- `RegulatorySource.schedule` (e.g. a cron expression) remains stored data with no interpreter; it does not cause anything to run automatically.

## Original API endpoint reference (unchanged)

`POST /api/v1/regulatory/sources/{source_id}/run` — no request body. Requires `require_configure`. Response: `IngestionRunResponse`, HTTP `202 Accepted`. `404` if the source doesn't exist, `400` if `enabled=False`.

## Remaining follow-up plan (not implemented this session)

1. ~~Immediate honesty fix (FAILED instead of eternal QUEUED)~~ — done, then superseded by the real RSS adapter above.
2. ~~RSS adapter~~ — done, this document.
3. **HTML adapter**: requires a per-source scraping strategy; higher risk of brittleness, should not be generalized into an unrestricted crawler (explicitly out of scope) — each HTML source needs its own targeted extraction rule.
4. **API/WEB_SERVICE adapter**: needs a per-source request/response mapping; no generic implementation is safe to write without knowing the specific regulator API's shape.
5. **Scheduler**: nothing currently triggers a run automatically; adding one is a separate, larger design question (polling interval, concurrency, failure backoff) not addressed here.
