# Decision Needed: Should ANALYST Be Able to Upload Documents and Trigger Impact Analysis?

Status: **UNRESOLVED — awaiting product-owner decision.** Implementation has proceeded with the conservative default (Option B below) so the rest of authorization enforcement was not blocked on this single question, but that default is not a substitute for an actual decision and should not be read as one.

## The existing proposal

`docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md` defines a role-permission matrix for every mutating endpoint in the API. Every cell in that matrix was derived mechanically from role names and the product's existing human-review posture, except this one.

## Exact operations affected

| Endpoint | Method | Effect |
|---|---|---|
| `POST /api/v1/regulatory/documents/upload` | POST | Introduces a new regulatory document into the organization's data |
| `POST /api/v1/regulatory/documents/{id}/process` | POST | Triggers deterministic (and, if configured, AI) extraction on an uploaded document |
| `POST /api/v1/impact/analyze` | POST | Runs the deterministic matching engine, creating an `ImpactAssessment` |
| `POST /api/v1/impact/{id}/reanalyze` | POST | Re-runs matching, creating a new assessment version |

Currently enforced default (`require_configure` in `app/api/dependencies/permissions.py`): `ADMIN`, `REGULATORY_MANAGER`, `COMPLIANCE_MANAGER` only. `ANALYST` receives `403` on all four.

## Option A — ANALYST can perform these operations

Add `UserRole.ANALYST` to `require_configure`'s allowed set (a one-line change in `app/api/dependencies/permissions.py`, already isolated there for exactly this reason).

**Consequences of allowing:**
- An analyst can independently upload source material and run analysis without needing a manager to do it for them — plausible if "analyst" in this organization means someone who actively works the regulatory pipeline, not just consumes its output.
- The seeded demo user `analyst@asterion.com` regains the ability to drive the full demo workflow interactively through the UI, not just view results created by others.
- Widens the set of roles that can introduce new data into the system and trigger (potentially AI-assisted) processing of it — a slightly larger surface for the prompt-injection mitigations in `app/ai/service.py` to matter against, though those mitigations are role-independent and unaffected either way.

## Option B — ANALYST remains read-only (current enforced default)

**Consequences of denying:**
- Matches the literal meaning of "analyst" in many compliance organizations: an observer/reporting role, not an operator.
- Safer default with less to unwind if wrong: loosening read-only → operate later is a backward-compatible one-line change; tightening operate → read-only later means revoking access people may have started relying on, which is disruptive.
- The seeded `analyst@asterion.com` demo user can read everything (assessments, changes, obligations, reviews, actions, audit trail) but cannot upload a document or trigger analysis through the UI — a manager-role demo user is needed to drive that part of a live walkthrough. The seed *scripts* are unaffected either way, since `app/seeds/demo_governance.py` drives services directly, not through this role check.

## Recommended default (already enforced, pending confirmation)

**Option B.** Chosen because it is the reversible direction: granting a permission later is a safe, additive change; revoking one that users have started depending on is not. This is a recommendation for what to ship *while waiting for a decision*, not a claim that the decision has been made.

## What would need to change if Option A is chosen instead

1. `app/api/dependencies/permissions.py`: add `UserRole.ANALYST` to `require_configure`'s tuple.
2. `app/tests/test_permissions.py::test_configure_matches_the_proposed_matrix`: move `ANALYST` from the denied list to the allowed list.
3. `app/tests/test_authorization_documents.py` and `test_authorization_impact.py`: move the `ANALYST` parametrized cases from "denied" to "allowed" tests.
4. `docs/security/AUTHORIZATION_MATRIX_PROPOSAL.md`: update the matrix table and remove the "open policy question" framing, replacing it with the decision and who made it.

None of this is implemented speculatively. It is listed here so that whoever makes this call can see the exact, small blast radius of either choice before deciding.
