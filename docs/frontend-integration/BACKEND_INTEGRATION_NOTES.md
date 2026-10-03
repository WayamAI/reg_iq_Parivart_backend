# PARIVART Backend — Frontend Integration Notes

Date: 2026-10-03. Scope: changes made in this work session on top of the existing,
already-largely-correct API. **The regulatory changes/obligations contract was checked
directly against the frontend repo (`reg_iq-main` / `services/api/intelligence.ts`,
`types.ts`) and already matches exactly — no contract change was made there.**

## 1. What actually changed this session (frontend-relevant)

### 1.1 Document processing status semantics — confirmed, not changed
`PARSED` is a legitimate terminal state, not just an in-flight step. If no AI provider
is registered/available (or `AI_ENRICHMENT_ENABLED=false`, the default), a document's
deterministic text extraction and version tracking still complete and the document is
left at `PARSED` — it is **not** relabelled `ANALYZED` (which would claim an AI pass that
never happened), and it is **not** marked `FAILED` either (the previous bug this session
fixed: `process_document` used to crash because `AIService()` raises when no provider is
registered, and that crash was caught and reported as `FAILED`, even though extraction
had succeeded).

Your frontend's `TERMINAL_DOCUMENT_STATES` already includes `PARSED` alongside `ANALYZED`
and `FAILED` (confirmed in `src/services/api/types.ts`) — **no change needed on your
side**, and your own code comment already documents having observed this exact behavior
live. This session's fix makes `PARSED` the *reliable, intended* outcome for "no AI ran"
rather than something that happened to work by making a crash non-fatal.

`GET /api/v1/regulatory/documents/{id}/status` response shape is unchanged:
```json
{ "document_id": "...", "processing_status": "PARSED" | "ANALYZED" | "FAILED" | ..., "parsed_at": "...". }
```

### 1.2 Regulatory changes / obligations — contract unchanged, already correct
`GET /api/v1/regulatory/changes/`, `GET /api/v1/regulatory/changes/{id}`,
`GET /api/v1/regulatory/changes/{id}/obligations`, `GET /api/v1/regulatory/obligations/`,
`GET /api/v1/regulatory/obligations/{id}` — all verified against your
`intelligence.ts`/`types.ts` and found to already match exactly: same paths, same
`skip`/`limit`/`document_id`/`change_type`/`regulatory_change_id`/`category` query
params, same bare-JSON-array response shape, same "404 not empty array" behavior for an
unknown/cross-tenant id. **No action needed on your side for this endpoint group.**

One backend-internal fix you may notice in the data: obligations created going forward
can now have a populated `change_id` where the extraction gives an unambiguous basis for
it (previously always `null`). This is additive — `change_id` was always `Optional` in
your `RegulatoryObligation` type and your code already handles it being present or
absent; nothing to change, but `GET /regulatory/changes/{id}/obligations` may now return
more obligations for a given change than it used to (previously it returned none, ever,
since nothing had `change_id` set).

### 1.3 Document upload deduplication — behavior changed, response shape unchanged
`POST /api/v1/regulatory/documents/upload` keeps the same response shape:
```json
{ "document_id": "...", "sha256": "...", "message": "...", "is_duplicate": true|false }
```
**Behavior fix**: deduplication is now scoped per-organization. Previously, if a
*different* organization had already uploaded byte-identical content, your organization's
upload would be reported as `is_duplicate: true` with a `document_id` belonging to the
other organization — which you could never actually fetch (`GET
/regulatory/documents/{document_id}` is tenant-scoped and would 404), since it was never
really your document. Now, the same content uploaded by two different organizations
creates two independent document records; `is_duplicate: true` only ever refers to a
document your own organization already has. If any UI code special-cased or logged a
duplicate-upload's `document_id` as "already visible to this org," that assumption is now
actually true (it was not reliably true before).

### 1.4 `/status` — new field, additive
```json
{
  "app": "PARIVART Backend API",
  "version": "0.1.0",
  "environment": "development",
  "database": { "status": "up", "error": null },
  "ai": {
    "enabled": false,
    "provider": "ollama",
    "model": "llama3.1",
    "provider_registered": false,
    "provider_status": null
  }
}
```
New field: `ai.provider_status` — `null` when no provider is registered for the
configured `provider`, otherwise an object with at least `provider`, `model`, and
provider-specific non-secret fields (e.g. `base_url`, `credential_configured` for Ollama
Cloud). **Never contains a credential value.** Purely additive; no existing field changed
shape or meaning. `provider_registered` is no longer always `false` by construction --
AI providers are now actually registered at startup (see below), so this will read `true`
whenever `AI_PROVIDER` matches a successfully-configured provider.

## 2. New backend capability: Ollama Cloud

Not previously implemented at all. Backend-only configuration (`OLLAMA_CLOUD_ENABLED`,
`OLLAMA_API_KEY`, `OLLAMA_CLOUD_MODEL`, etc. — see
`docs/engineering-audit/08-ai-provider-and-ollama-integration-status.md` for the full
list). **No frontend change is required or possible here** — there is no new API surface
for this; it only affects whether `ai.provider_registered`/`ai.provider_status` on
`/status` reflect a working cloud provider, and whether an `ImpactAssessment`'s
`ai_enrichment_status`/`ai_narrative` fields (already part of your existing
`ImpactAssessmentResponse` type, unchanged) can reach `SUCCESS` with real content instead
of always resolving to `UNAVAILABLE`.

## 3. Authentication — unchanged, re-confirmed safe

`DEMO_AUTH_ALLOW_ANY` behavior and gating are unchanged. Re-confirmed in this session:
double-gated by `APP_ENV=="development"`, so it cannot activate in a production
deployment regardless of the flag's value there. No frontend-visible change.

## 4. Known limitations carried forward (not fixed this session)

- Automated regulatory-source ingestion (`POST /regulatory/sources/{id}/run`) still only
  creates a `QUEUED` `IngestionRun` row; no document is actually fetched. If your UI
  polls `GET /sources/{id}/runs` expecting a run to progress past `QUEUED`, it will not,
  for any source, today.
- No role-based authorization is enforced at the API layer beyond "is an authenticated,
  active user of some organization" — every authenticated user currently has the same
  write access regardless of `role`. If your UI hides controls by role, the backend will
  still accept the underlying request from a user whose role would suggest otherwise.

## 5. Upload file constraints

Unchanged: `POST /regulatory/documents/upload` accepts `multipart/form-data` with
`file`, `title`, `authority_id`, `source_id` required; `description`, `document_type`,
`jurisdiction`, `country`, `source_url` optional. Supported extraction MIME types:
`application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
(.docx), `text/html`, `text/plain`. An unsupported MIME type extracts as `None` and the
document is marked `FAILED` (this is a real, unchanged failure path — distinct from the
AI-unavailable case, which now correctly stays at `PARSED`).

## 6. Questions for the frontend engineer to flag back

- Does any UI code assume `provider_registered` is always `false` (e.g. hiding an
  "AI-enriched" badge unconditionally)? That assumption no longer holds in an environment
  where `AI_PROVIDER=ollama` (the default) and a local Ollama daemon happens to be
  reachable, or where Ollama Cloud is configured.
- Does any UI code treat a duplicate-upload response's `document_id` as potentially
  belonging to a document it cannot fetch? That should no longer happen, but worth a
  quick check of any defensive handling that assumed it might.
