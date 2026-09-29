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

---

## Organization Isolation

Every endpoint above is scoped to the authenticated user's organization. A resource owned
by another organization is reported as **404, never 403**, so an id cannot be probed for
existence. This is enforced in the backend query, not by client-side filtering.
