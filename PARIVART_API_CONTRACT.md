# PARIVART API Contract

This document establishes the canonical API contract between the PARIVART FastAPI Backend and the PARIVART Frontend (`Niyo360`).

## Base URL
`/api/v1`

## Standard Response Envelope

All successful responses return JSON. **List endpoints return a bare JSON array**, not a
pagination envelope. Paging is by `skip` and `limit` query parameters, and the total is
not returned:

```json
[ { "id": "...", "...": "..." } ]
```

Earlier revisions of this document described an `{items, page, page_size, total,
total_pages}` envelope. No endpoint has ever returned that shape; the description above
is what the API actually sends.

Standard Error Envelope — every deliberate error and every unhandled exception:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Human readable description",
    "request_id": "d5c5322f-e6df-4238-bbdd-e91dcb78844f"
  },
  "detail": "Human readable description"
}
```

`detail` is retained alongside `error` so clients written against FastAPI's default shape
keep working. The same correlation id is returned in the `X-Request-ID` response header,
which is listed in `Access-Control-Expose-Headers` so browser JavaScript can read it.
Stack traces, SQL and configuration never appear in a response body.

### Status codes

| Code | Meaning in this API |
|------|---------------------|
| 400  | Malformed request that schema validation cannot express |
| 401  | Missing, invalid or expired token; inactive user |
| 403  | Authenticated but not permitted |
| 404  | Not found **or owned by another organization** — the two are deliberately indistinguishable |
| 409  | Conflicts with current state (e.g. an illegal action status transition) |
| 422  | Request body failed schema validation |
| 500  | Unhandled server error; safe envelope with a request id, never a stack trace |

---

## Endpoints Summary

### 1. Authentication (`/api/v1/auth`)
- `POST /api/v1/auth/register` — Register a new user/organization
- `POST /api/v1/auth/login` — Obtain JWT access token (form-encoded `username`/`password`)
- `GET /api/v1/auth/me` — Current user profile

There is **no** `POST /api/v1/auth/logout`. Access tokens are stateless JWTs and are not
tracked server-side, so a client logs out by discarding its token. A client calling
`/auth/logout` will receive 404. Deactivating a user (`is_active = false`) invalidates
their existing tokens immediately, because `get_current_user` re-checks the flag on every
request.

### 2. Regulatory Authorities & Sources (`/api/v1/regulatory`)
- `GET /api/v1/regulatory/authorities`
- `POST /api/v1/regulatory/authorities`
- `GET /api/v1/regulatory/sources`
- `POST /api/v1/regulatory/sources`
- `POST /api/v1/regulatory/sources/{id}/run`
- `GET /api/v1/regulatory/sources/{id}/runs`

### 3. Documents (`/api/v1/regulatory/documents`)
- `GET /api/v1/regulatory/documents`
- `POST /api/v1/regulatory/documents/upload` (Supports PDF, DOCX, HTML, TXT)
- `GET /api/v1/regulatory/documents/{id}`
- `POST /api/v1/regulatory/documents/{id}/process`
- `GET /api/v1/regulatory/documents/{id}/status`

### 4. Portfolio Management (`/api/v1/portfolio`)
- `GET /api/v1/portfolio/products` & `POST`
- `GET /api/v1/portfolio/markets` & `POST`
- `GET /api/v1/portfolio/processes` & `POST`
- `GET /api/v1/portfolio/controls` & `POST`
- `GET /api/v1/portfolio/registrations` & `POST`

### 5. Impact Assessments (`/api/v1/impact`)
- `POST /api/v1/impact/analyze` — Run deterministic portfolio matching for a regulatory
  change. Makes no AI call, so it always completes; optional AI enrichment is scheduled
  in the background and reported via `ai_enrichment_status`
- `GET /api/v1/impact` — List impact assessments
- `GET /api/v1/impact/{id}` — Get full impact assessment and items
- `GET /api/v1/impact/{id}/items` — List items for an assessment
- `POST /api/v1/impact/{id}/reanalyze` — Force re-analysis

### 6. Impact Delta Reports (`/api/v1/reports`)
- `POST /api/v1/reports/generate` — Generate a versioned Impact Delta Report
  (`FACT`, `SOURCE_EVIDENCE`, `RESULTING_OBLIGATIONS`, `SYSTEM_INTERPRETATION`,
  `AI_ENRICHMENT`, `HUMAN_DECISION`)
- `GET /api/v1/reports` — List generated reports
- `GET /api/v1/reports/{id}` — Get report details and structured data
- `GET /api/v1/reports/{id}/versions` — Get version history for a report

### 7. Human Review (`/api/v1/reviews`)

A review is a human decision recorded against an impact assessment. Rows are
**append-only**: a reviewer who changes their mind files a new review, and the earlier one
is never rewritten. There is deliberately no update or delete endpoint.

- `POST /api/v1/reviews/` — File a decision. Body: `impact_assessment_id`, `decision`,
  optional `notes`.
  - The reviewer is taken from the access token. `reviewer_id` in the body is ignored.
  - `decision` is one of `ACCEPT`, `MODIFY`, `REJECT`, `NEEDS_MORE_INFORMATION`.
  - Moves the assessment: `ACCEPT`/`MODIFY` → `REVIEWED`, `REJECT`/`NEEDS_MORE_INFORMATION`
    → `REQUIRES_REVIEW`. The response records `previous_state` and `new_state`.
  - `409` if the assessment is not reviewable yet (`PENDING`, `ANALYZING`, `FAILED`).
  - `404` if the assessment does not exist or belongs to another organization.
- `GET /api/v1/reviews/` — The organization's review trail, newest first. Optional
  `impact_assessment_id`, `reviewer_id`, `skip`, `limit`. With no filter this returns the
  whole trail for the organization, not an empty list.
- `GET /api/v1/reviews/{id}` — A single review.

### 8. Actions (`/api/v1/actions`)

- `POST /api/v1/actions/` — Open an action. Body: `title`, optional `description`,
  `owner_id`, `impact_item_id`, `priority` (`LOW`/`MEDIUM`/`HIGH`), `due_date`.
  - The owning organization is taken from the access token. `organization_id` in the body
    is ignored.
  - `404` if `owner_id` is not a member of the organization, or `impact_item_id` does not
    belong to one of the organization's assessments.
- `GET /api/v1/actions/` — The organization's actions, newest first. Optional `owner_id`,
  `impact_item_id`, `status`, `skip`, `limit`. Passing `due_within_days` instead returns
  open work due inside that window, soonest first.
- `GET /api/v1/actions/{id}` — A single action.
- `PATCH /api/v1/actions/{id}` — Partial update. May include `status`, which is checked
  against the same state machine as the dedicated endpoint.
- `PATCH /api/v1/actions/{id}/status` — Body: `{"status": "IN_PROGRESS"}`. The status is
  in the **body**, not the query string.

Action state machine. `COMPLETED` and `CANCELLED` are terminal — a closed action is never
reopened, because evidence and audit records reference the closed state. An illegal
transition is `409`. Re-sending the current status is a no-op, not an error.

```text
OPEN         -> IN_PROGRESS, BLOCKED, COMPLETED, CANCELLED
IN_PROGRESS  -> OPEN, BLOCKED, COMPLETED, CANCELLED
BLOCKED      -> OPEN, IN_PROGRESS, COMPLETED, CANCELLED
COMPLETED    -> (terminal)
CANCELLED    -> (terminal)
```

`completed_at` is stamped on entry into `COMPLETED` and is null for every other status.

### 9. Evidence (`/api/v1/evidence`)

Files that substantiate an action.

- `POST /api/v1/evidence/upload` — **`multipart/form-data`**: `file` (required),
  `action_id` (required), `description` (optional). `201` with the created record.
  The uploader and the tenant come from the access token, never the form.
- `GET /api/v1/evidence/` — Query: `action_id`, `skip`, `limit`. Bare array, newest first.
- `GET /api/v1/evidence/{id}`
- `GET /api/v1/evidence/{id}/download` — streams the stored bytes as an attachment.

Evidence attaches to an **action and nothing else**. The `evidence` table carries an
`action_id` with no generic `entity_type`/`entity_id` pair, so evidence reaches the rest
of the chain through the action it belongs to:

```text
evidence -> action -> impact item -> assessment -> regulatory change -> document
```

There is **no `evidence_type`** field or enum — no such column exists.

`storage_key` is **never serialised**. It is an internal filesystem path; retrieval goes
through the download endpoint, which resolves the key server-side after checking the
tenant.

Ownership of the action is checked **before the file is stored**, so a request naming
another tenant's action writes nothing at all and returns `404`.

Evidence is **not deduplicated by `sha256`**, unlike a regulatory document. The same file
may legitimately substantiate two actions, and refusing the second would lose the fact
that it was offered for both. The hash is an integrity anchor, not a uniqueness
constraint.

`GET /{id}/download` returns **`410`**, not `404`, when the row exists but its stored file
does not. A `404` would claim the evidence was never filed, which is a different and more
alarming statement than "the file is no longer available".

### 10. Audit Trail (`/api/v1/audit`)

- `GET /api/v1/audit/` — Query: `entity_type`, `entity_id`, `actor_id`, `event_type`,
  `since`, `until`, `skip`, `limit`. Bare array, newest first.
- `GET /api/v1/audit/{id}`
- `GET /api/v1/audit/event-types` — the vocabulary this backend writes, so a client can
  build a filter without hardcoding a list that would drift. It describes what *can* be
  written, not what a given organization has.

**Read-only. `POST`, `PATCH` and `DELETE` are `405`.** Audit events are written by the
services as a side effect of a real change, never posted by a client: a trail a caller
can write to proves nothing, and one a caller can edit is not a trail. The only way to
add an event is to make the change it describes.

`entity_type` + `entity_id` together answer "the history of this record", which is how a
detail screen links to its own provenance.

An event names its actor — `actor_id`, `actor_name`, `actor_email` — so a reader does not
have to resolve a UUID to learn who acted. `actor_*` are null for an event with no
attributable user.

`payload` arrives as a **JSON object**, parsed from the JSON string held in the `Text`
column. A historical row whose payload does not parse is reported as having none rather
than raising, so one malformed detail cannot make the rest of the trail unreadable.

`event_type` and `entity_type` are **plain strings, not enums**, matching their columns.
Reading is deliberately tolerant: an event written by another revision still reads back
and still renders. A client maps the values it knows to labels and falls back to the raw
value.

Event types currently written:

```text
USER_SIGNED_IN                    DOCUMENT_UPLOADED
IMPACT_ASSESSMENT_CREATED         DOCUMENT_PROCESSED
IMPACT_ASSESSMENT_REANALYZED      REPORT_GENERATED
REVIEW_FILED                      ACTION_CREATED
ACTION_UPDATED                    ACTION_STATUS_CHANGED
EVIDENCE_ATTACHED
```

Entity types: `USER`, `REGULATORY_DOCUMENT`, `IMPACT_ASSESSMENT`, `IMPACT_REPORT`,
`ACTION`.

What is deliberately **not** recorded:

- A **failed** sign-in. Failed attempts belong in the security log, not in a
  tenant-readable trail, and recording them would mean writing rows on behalf of a caller
  who never authenticated.
- A **refused** change. An illegal action transition raises before anything is recorded
  and nothing is committed, so the trail cannot claim a change the state machine rejected.
- A **no-op**. Re-sending an action's current status is allowed and is not a change. A
  duplicate document upload returns at the dedupe check, before any row is added. A
  reused (idempotent) analysis ran no analysis.
- **Free text and secrets.** A payload carries ids, enum values, changed field *names* and
  before/after states. An action edit records which fields changed, not their values; a
  review records *whether* a note was left, not the note. No token, credential, password
  hash, file byte or document text is ever written to a payload.

Every event is recorded **inside the transaction that makes the change it describes**, so
a change and its event succeed or fail together.

### 11. Regulatory Intelligence (`/api/v1/regulatory`)

Read-only access to what the document-processing pipeline extracted.

- `GET /api/v1/regulatory/changes/` — Query: `document_id`, `change_type`, `skip`, `limit`
- `GET /api/v1/regulatory/changes/{id}`
- `GET /api/v1/regulatory/changes/{id}/obligations`
- `GET /api/v1/regulatory/obligations/` — Query: `regulatory_change_id`, `document_id`,
  `category`, `skip`, `limit`
- `GET /api/v1/regulatory/obligations/{id}`

These close a real gap: an impact assessment carries a `regulatory_change_id` that
previously no endpoint could resolve, so a client could show the id and the engine's
summary but could not link through to the change or list the obligations behind a match.

**Read-only, and `405` on writes.** These rows are what the pipeline extracted from a
source document, not user-entered data. Hand-editing an extracted obligation would
destroy the provenance that makes it worth anything.

**Tenancy runs through the document.** Neither `regulatory_changes` nor
`regulatory_obligations` has an `organization_id`; ownership is established by joining
`regulatory_documents` and filtering on its `organization_id`.

`GET /changes/{id}/obligations` for an unknown or cross-tenant change is a `404`, not an
empty list — "this change has no obligations" and "you cannot see this change" are
different answers and should not look alike.

`confidence` is `Numeric(3,2)` in the database and is serialised as a JSON **number**.

---

## Organization Isolation

Every endpoint above is scoped to the authenticated user's organization. A resource owned
by another organization is reported as **404, never 403**, so an id cannot be probed for
existence. This is enforced in the backend query, not by client-side filtering.
