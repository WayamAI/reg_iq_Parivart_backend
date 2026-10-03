# Authorization Matrix — Proposal

Date: 2026-10-03. Status: **PROPOSED, NOT YET APPROVED OR ENFORCED**. This document exists to let implementation proceed on the parts that don't depend on a policy call, and to make the one real policy decision explicit rather than guessed.

## Existing roles (source: `app/models/user.py`)

```python
class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    REGULATORY_MANAGER = "REGULATORY_MANAGER"
    COMPLIANCE_MANAGER = "COMPLIANCE_MANAGER"
    REVIEWER = "REVIEWER"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"
```
No new role is proposed here. A `User` has exactly one role (`User.role`, not a set), consistent with the existing single-organization-membership model.

## Permission classes

| Class | Meaning |
|---|---|
| **READ** | `GET` endpoints — viewing data already scoped to the caller's organization |
| **OPERATE** | Day-to-day write actions: uploading documents, triggering analysis, creating/transitioning actions, uploading evidence |
| **APPROVE** | Filing a human review decision (`ImpactReview`) — the product's explicit human-judgment gate |
| **CONFIGURE** | Managing portfolio structure and regulatory source/authority configuration — changes what the matching engine computes against, not a day-to-day action |
| **ADMIN** | User/organization-settings management — not implemented in the API today (see note below) |

## Proposed role → permission-class mapping

| Role | READ | OPERATE | APPROVE | CONFIGURE | ADMIN |
|---|---|---|---|---|---|
| `VIEWER` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `ANALYST` | ✅ | ✅ (trigger analysis only — see below) | ❌ | ❌ | ❌ |
| `REVIEWER` | ✅ | ✅ (actions/evidence only) | ✅ | ❌ | ❌ |
| `REGULATORY_MANAGER` | ✅ | ✅ | ❌ | ✅ | ❌ |
| `COMPLIANCE_MANAGER` | ✅ | ✅ | ✅ | ✅ | ❌ |
| `ADMIN` | ✅ | ✅ | ✅ | ✅ | ✅ |

## Proposed per-operation matrix

| Operation | Endpoint(s) | Allowed roles |
|---|---|---|
| Read regulatory data (authorities, sources, documents, changes, obligations) | `GET /regulatory/*` | All roles |
| Create/update/delete sources and authorities | `POST/PATCH/DELETE /regulatory/{authorities,sources}` | `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER` |
| Trigger ingestion | `POST /regulatory/sources/{id}/run` | `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER` |
| Upload documents | `POST /regulatory/documents/upload` | `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER`, `ANALYST` |
| Trigger document processing | `POST /regulatory/documents/{id}/process` | Same as upload |
| Read changes/obligations | `GET /regulatory/{changes,obligations}` | All roles |
| Manage products/markets/processes/controls/registrations | `POST/PATCH/DELETE /portfolio/*` | `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER` |
| Create/reanalyze impact assessments | `POST /impact/analyze`, `POST /impact/{id}/reanalyze` | `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER`, `ANALYST` |
| Read impact assessments | `GET /impact/*` | All roles |
| File a review decision | `POST /reviews/` | `ADMIN`, `COMPLIANCE_MANAGER`, `REVIEWER` |
| Read reviews | `GET /reviews/*` | All roles |
| Create/update/transition actions | `POST/PATCH /actions/*` | `ADMIN`, `COMPLIANCE_MANAGER`, `REGULATORY_MANAGER`, `REVIEWER` |
| Upload evidence | `POST /evidence/upload` | Same as actions |
| Download/read evidence | `GET /evidence/*` | All roles (see Sensitive operations below) |
| Read audit events | `GET /audit/*` | All roles |
| Manage users/organization settings | *(no such endpoint exists today)* | N/A — out of scope until such an endpoint exists |

## Tenant isolation requirements (unchanged, independent of role)

Role enforcement is **additive to**, never a **replacement for**, the existing per-`organization_id` scoping already confirmed consistent across every router in `AUTHORIZATION_GAPS.md`. A `COMPLIANCE_MANAGER` in organization A must still receive `404` — not `200`, and not `403` — for a resource belonging to organization B. No change to this behavior is proposed.

## Sensitive operations needing explicit attention

- **Evidence download** (`GET /evidence/{id}/download`): proposed as all-roles-readable within an organization, consistent with evidence being compliance documentation every org member may need to reference. If this is judged too permissive (e.g., only `REVIEWER`+ should download), that is the kind of call this document exists to surface rather than guess — flagged as **Option 2** below.
- **Regulatory source/authority configuration**: global (not tenant-scoped) data. Under the current implementation, any authenticated user editing a source affects every tenant. This proposal does not change that scope — only adds a role gate on top of it — but it is worth noting that role-gating alone does not fix the global-source-mutation surface; that is a separate, larger design question out of scope here.

## Fail-closed behavior

The proposed `require_role()` dependency denies by default: a role not explicitly listed for an operation is rejected, not allowed. This includes any future role added to `UserRole` that this document doesn't yet account for — it would need an explicit addition to the mapping before gaining any permission, rather than inheriting broad access by omission.

## Compatibility with existing demo users

`app/seeds/demo_data.py` seeds `admin@asterion.com` (`ADMIN`) and `analyst@asterion.com` (`ANALYST`). Under this proposal:
- `admin@asterion.com` keeps full access — unaffected.
- `analyst@asterion.com` keeps read access everywhere, keeps the ability to upload documents and trigger impact analysis, but **loses** the ability to create/modify portfolio data, manage sources, file reviews, or manage actions/evidence — all of which the demo scripts exercise via services directly (`ActionService`, `ReviewService`, `EvidenceService` in `app/seeds/demo_governance.py`), not via the analyst's HTTP session, so the demo seed itself is unaffected. A manual walkthrough of the deployed demo UI as the analyst user would be affected if it currently exercises any of those operations — this should be checked before enforcement ships, not assumed safe.

## The one genuine policy decision this document surfaces

**Should `ANALYST` be permitted to trigger impact analysis and document uploads (OPERATE on those two specific endpoints), or should `ANALYST` be strictly read-only, matching the literal meaning of "analyst" in many compliance orgs as an observer/reporting role rather than an operator?**

Two defensible options:
1. **(Proposed above)** `ANALYST` can upload documents and trigger analysis — useful for the seeded demo workflow, and consistent with an analyst's job being to run analyses, not just read their output.
2. **Stricter**: `ANALYST` is READ-only everywhere, identical to `VIEWER` in permission terms but distinct in name/reporting context. This is simpler to reason about and a safer default, at the cost of the seeded `analyst@asterion.com` user losing the ability to drive the demo workflow interactively (though, as noted, the seed script itself does not depend on this).

**This decision is not made by this document.** Section A3 implementation below proceeds with every role-gate EXCEPT the two `ANALYST`-specific OPERATE grants (document upload, impact analysis trigger) left out of the enforced matrix until this is resolved — `ANALYST` is treated as READ-only in the initial enforced version, since that is the stricter, safer default and is trivially loosened later (adding a permission is backward compatible; removing one that users have started depending on is not).

## Tests required before this is considered enforced (see `app/tests/test_authorization.py`)

- Every `(role, operation)` cell in the matrix above has at least one test.
- Unauthenticated request → `401` for every operation.
- A role not in `UserRole` at all (simulated) → `403`, never `200` (fail-closed default).
- Cross-tenant object access is denied the same way (`404`) for every role, including `ADMIN` — role does not grant cross-tenant visibility.
- Demo users (`admin@asterion.com`, `analyst@asterion.com`) retain exactly the access this document says they should.
