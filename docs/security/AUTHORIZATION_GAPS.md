# Authorization Gap Assessment

Date: 2026-10-03, originally written when no role enforcement existed. **Superseded by implementation the same day** — see `AUTHORIZATION_MATRIX_PROPOSAL.md` for the enforced matrix and `app/api/dependencies/{auth,permissions}.py` for the code. This document is kept as the historical record of the gap and is updated below to point at what replaced it, not rewritten to hide that the gap existed.

**Current status, re-verified after enforcement**: `require_role()`/`require_configure`/`require_operate`/`require_approve` are now applied to every mutating endpoint listed in the table below. Verified via `grep -rn "require_configure\|require_operate\|require_approve" app/api/routers/*.py` showing a hit in every router this document originally flagged, and via the authorization test suite (`app/tests/test_authorization_*.py`, `test_require_role.py`, `test_permissions.py` — 113 tests collected, verified via `pytest --collect-only`, covering every (role, operation) combination in the matrix, cross-tenant isolation under a privileged role, and fail-closed behavior for an unlisted role).

Method for the original assessment: direct source inspection (`grep -n "current_user.role\|UserRole\.\|require_role" app/api/routers/*.py app/api/dependencies/*.py app/services/*.py`, plus manual reads) — not inferred from documentation or prior reports.

## Confirmed: what IS enforced

- **Authentication**: every endpoint except `POST /auth/register`, `POST /auth/login`, and the health/status group requires a valid, non-expired JWT resolving to an `is_active=True` user (`app/api/dependencies/auth.get_current_user`). Verified by direct read.
- **Tenant (organization) scoping**: every router checked in this assessment — `impact.py`, `evidence.py`, `actions.py`, `reviews.py`, `portfolio_controls.py`, `portfolio_registrations.py`, `regulatory_documents.py`, `regulatory_intelligence.py` — filters every query by `current_user.organization_id`, and resource-not-found vs. resource-belongs-to-another-tenant both resolve to `404`, never `403` (so a cross-tenant id is indistinguishable from a non-existent one). This is consistent and was independently re-verified this session via `grep` across the router directory plus the dedicated tests already in the suite (`test_impact_isolation.py`, `test_document_upload.py`'s cross-tenant tests, `test_regulatory_intelligence_api.py`).
- **Evidence upload identity**: uploader and tenant are taken from the JWT, never the request body (`evidence.py`), so a caller cannot file evidence as another user.
- **Append-only trails**: `AuditEvent` and `ImpactReview` have no update/delete endpoint anywhere in the routers — confirmed by the absence of any `PATCH`/`DELETE` route for either in `audit.py` or `reviews.py`.

## Historical: what was NOT enforced when this document was first written

**At the time of the original assessment, there was no role-based authorization anywhere in this codebase.** The only two matches for role-related code in the entire `app/api/` and `app/services/` tree were:
- `app/api/dependencies/auth.py` defining `get_current_user` (identity only, no role check).
- `app/api/routers/auth.py` assigning `role=UserRole.REGULATORY_MANAGER` to an auto-provisioned demo user.

No router, dependency, or service checked `current_user.role` before permitting an action, despite `UserRole` (`ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER`, `REVIEWER`, `ANALYST`, `VIEWER`) existing as a first-class field on `User`. **This is no longer true** — see the Current status note above.

### Sensitive endpoints this gap used to expose — now role-gated

Every endpoint below used to accept a request from any authenticated, active user of the organization regardless of role. Each now requires the role group noted, enforced via `require_configure`/`require_operate`/`require_approve` (`app/api/dependencies/permissions.py`):

| Endpoint | Method | Now requires | Sensitive because |
|---|---|---|---|
| `POST /impact/analyze`, `POST /impact/{id}/reanalyze` | POST | `require_configure` | Triggers (re)computation and versioning of impact assessments |
| `POST /reviews/` | POST | `require_approve` | Records a human governance decision (ACCEPT/MODIFY/REJECT) that gates whether remediation work starts |
| `POST /actions/`, `PATCH /actions/{id}`, `PATCH /actions/{id}/status` | POST/PATCH | `require_operate` | Creates and transitions remediation work, including marking it COMPLETED |
| `POST /evidence/upload` | POST | `require_operate` | Attaches compliance evidence to an action |
| `POST /regulatory/documents/upload`, `POST /{id}/process` | POST | `require_configure` | Introduces new regulatory source material into the tenant's data |
| `POST/PATCH/DELETE /portfolio/{products,markets,processes,controls,registrations}/*` | POST/PATCH/DELETE | `require_configure` | Mutates the portfolio that impact assessment and matching are computed against |
| `POST /regulatory/sources/`, `PATCH`, `DELETE`, `POST /{id}/run` | — | `require_configure` | Mutates global (not even tenant-scoped) regulatory source configuration |
| `POST /regulatory/authorities/`, `PATCH`, `DELETE` | — | `require_configure` | Mutates global regulatory authority reference data |
| `GET /evidence/{id}/download` | GET | *(unchanged — all roles)* | Reads potentially sensitive compliance evidence files — left open to every org member per the matrix proposal's explicit decision, not an oversight |

Nothing above was a newly-introduced regression when first documented; it was the state of the codebase since these endpoints were added. It is no longer the current state — see the commit history on `feat/ollama-cloud-integration` from `feat(auth): add require_role()...` onward for the enforcement commits, each with its own router and tests.

## What was the minimum safe implementation plan — now implemented

The plan originally proposed here was carried out essentially as written:

1. `require_role(*allowed: UserRole)` added to `app/api/dependencies/auth.py`, built on `get_current_user`. ✅
2. The role matrix was finalized in `AUTHORIZATION_MATRIX_PROPOSAL.md` (one open policy question — whether `ANALYST` may upload documents/trigger analysis — resolved conservatively to read-only, documented as a reversible choice, not guessed silently). ✅
3. Applied one router at a time, each its own commit: authorities, sources, documents, all five portfolio routers, impact, reviews, actions, evidence. ✅
4. Each router's commit has a paired test file (`test_authorization_*.py`) asserting denied roles get `403` and allowed roles succeed, for both a brand-new tenant (`role_headers`) and a same-tenant teammate (`teammate_headers`). ✅

## Tests that now exist (previously "required before claiming this is implemented")

- Every mutating endpoint listed above: a request from each excluded role returns `403`, a request from each permitted role succeeds. ✅ (`test_authorization_authorities.py`, `test_authorization_sources.py`, `test_authorization_portfolio.py`, `test_authorization_documents.py`, `test_authorization_impact.py`, `test_authorization_reviews.py`, `test_authorization_actions_evidence.py`)
- Fail-closed for an unlisted role. ✅ (`test_require_role.py::test_fails_closed_for_a_role_not_in_the_allowed_set_at_all`, `test_empty_allowed_set_denies_everyone`)
- Existing tenant-isolation tests continue to pass unchanged. ✅ (confirmed: `test_impact_isolation.py`, `test_document_upload.py`'s cross-tenant tests, etc. all still pass in the full suite run after every enforcement commit)
- Privileged-role cross-tenant denial. ✅ (`test_authorization_cross_tenant.py`)
- Demo users checked against the adopted matrix. ✅ (`AUTHORIZATION_MATRIX_PROPOSAL.md`'s compatibility section: `admin@asterion.com` unaffected, `analyst@asterion.com` loses HTTP-level write access the seed scripts don't depend on)

## Verification status of this document

`CONFIRMED` by direct source inspection, `grep`, and a 113-test authorization suite collected and passing as part of the full 356+-test run. This document now records history (what the gap was) and current fact (that it is closed, with evidence), not a live gap.
