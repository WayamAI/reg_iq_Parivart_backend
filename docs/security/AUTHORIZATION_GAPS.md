# Authorization Gap Assessment

Date: 2026-10-03. Method: direct source inspection (`grep -n "current_user.role\|UserRole\.\|require_role" app/api/routers/*.py app/api/dependencies/*.py app/services/*.py`, plus manual reads) — not inferred from documentation or prior reports.

## Confirmed: what IS enforced

- **Authentication**: every endpoint except `POST /auth/register`, `POST /auth/login`, and the health/status group requires a valid, non-expired JWT resolving to an `is_active=True` user (`app/api/dependencies/auth.get_current_user`). Verified by direct read.
- **Tenant (organization) scoping**: every router checked in this assessment — `impact.py`, `evidence.py`, `actions.py`, `reviews.py`, `portfolio_controls.py`, `portfolio_registrations.py`, `regulatory_documents.py`, `regulatory_intelligence.py` — filters every query by `current_user.organization_id`, and resource-not-found vs. resource-belongs-to-another-tenant both resolve to `404`, never `403` (so a cross-tenant id is indistinguishable from a non-existent one). This is consistent and was independently re-verified this session via `grep` across the router directory plus the dedicated tests already in the suite (`test_impact_isolation.py`, `test_document_upload.py`'s cross-tenant tests, `test_regulatory_intelligence_api.py`).
- **Evidence upload identity**: uploader and tenant are taken from the JWT, never the request body (`evidence.py`), so a caller cannot file evidence as another user.
- **Append-only trails**: `AuditEvent` and `ImpactReview` have no update/delete endpoint anywhere in the routers — confirmed by the absence of any `PATCH`/`DELETE` route for either in `audit.py` or `reviews.py`.

## Confirmed: what is NOT enforced

**There is no role-based authorization anywhere in this codebase.** The only two matches for role-related code in the entire `app/api/` and `app/services/` tree are:
- `app/api/dependencies/auth.py` defining `get_current_user` (identity only, no role check).
- `app/api/routers/auth.py` assigning `role=UserRole.REGULATORY_MANAGER` to an auto-provisioned demo user.

No router, dependency, or service anywhere checks `current_user.role` before permitting an action, despite `UserRole` (`ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER`, `REVIEWER`, `ANALYST`, `VIEWER`) existing as a first-class field on `User`.

### Sensitive endpoints exposed by this gap

Every one of the following currently accepts a request from **any** authenticated, active user of the organization, regardless of role — including a `VIEWER`, which the role name itself implies should be read-only:

| Endpoint | Method | Sensitive because |
|---|---|---|
| `POST /impact/analyze`, `POST /impact/{id}/reanalyze` | POST | Triggers (re)computation and versioning of impact assessments |
| `POST /reviews/` | POST | Records a human governance decision (ACCEPT/MODIFY/REJECT) that gates whether remediation work starts |
| `POST /actions/`, `PATCH /actions/{id}`, `PATCH /actions/{id}/status` | POST/PATCH | Creates and transitions remediation work, including marking it COMPLETED |
| `POST /evidence/upload` | POST | Attaches compliance evidence to an action |
| `POST /regulatory/documents/upload`, `POST /{id}/process` | POST | Introduces new regulatory source material into the tenant's data |
| `POST/PATCH/DELETE /portfolio/{products,markets,processes,controls,registrations}/*` | POST/PATCH/DELETE | Mutates the portfolio that impact assessment and matching are computed against |
| `POST /regulatory/sources/`, `PATCH`, `DELETE`, `POST /{id}/run` | — | Mutates global (not even tenant-scoped) regulatory source configuration |
| `GET /evidence/{id}/download` | GET | Reads potentially sensitive compliance evidence files — any org member can download any evidence their organization has, regardless of role |

Nothing above is a newly-introduced regression; this has been the state of the codebase since these endpoints were added (confirmed via `git log` on the relevant files — none show a role check being added or removed).

## Minimum safe implementation plan (not implemented this session — see rationale below)

A safe, minimal RBAC layer that fits the existing model without inventing a new one:

1. Add a `require_role(*allowed: UserRole)` FastAPI dependency in `app/api/dependencies/auth.py`, built on top of the existing `get_current_user` (same pattern already used for tenant scoping — no new architecture).
2. Define, in one place, which roles may perform which class of action. A defensible first cut, derived directly from the existing role names and the product's own conservative-review posture (humans must approve impact findings before action is taken):
   - **Write portfolio data, manage sources/authorities**: `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER`.
   - **File a review decision**: `ADMIN`, `COMPLIANCE_MANAGER`, `REVIEWER`.
   - **Create/transition actions, upload evidence**: `ADMIN`, `COMPLIANCE_MANAGER`, `REGULATORY_MANAGER`, `REVIEWER`.
   - **Trigger impact analysis**: `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER`, `ANALYST`.
   - **Read-only everywhere** (`GET`): every role including `VIEWER`.
3. Apply `require_role(...)` to each mutating endpoint's `Depends(...)` list, one router at a time, as its own commit, so each change is independently reviewable and testable.
4. For each router touched, add a test asserting a `VIEWER` (or whichever role is excluded) receives `403` on the mutating endpoint and `200` on the corresponding `GET`.

### Why this was not implemented in this session

This is a genuine policy decision (which role may do what), not a mechanical bug fix — the plan above is a reasonable first cut, but assigning it unilaterally risks locking in an incorrect access model that then has to be unwound. Per this task's explicit instruction not to introduce a speculative or incompatible role model without the product owner's confirmation, this document records the gap, the evidence, and a concrete, minimal, test-covered plan, without marking the gap as resolved.

## Tests required before claiming this is implemented

- For every mutating endpoint listed above: a request from each excluded role returns `403`, and a request from each permitted role succeeds (status code matching today's documented behavior).
- A request from a role with NO explicit permission entry (a new role added later) defaults to denied, not allowed — i.e. the dependency should be allow-list, not deny-list, and this default-deny behavior itself should have a test.
- Existing tenant-isolation tests must continue to pass unchanged — role checks are additive to, not a replacement for, organization scoping.
- The demo seed's two users (`admin@asterion.com` role `ADMIN`, `analyst@asterion.com` role `ANALYST`) should be checked against whatever role matrix is adopted, so the demo environment does not accidentally lock out its own analyst account from read-only exploration.

## Verification status of this document

`CONFIRMED` by direct source inspection and `grep` (not inferred): no role check exists anywhere in `app/api/` or `app/services/`. Tenant scoping is `CONFIRMED` present and consistent in every router read during this assessment. The implementation plan above is `PROPOSED`, not implemented.
