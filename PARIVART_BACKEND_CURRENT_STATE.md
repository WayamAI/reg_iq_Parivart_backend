# PARIVART Backend Implementation Status

## Phase 1: Foundation & Authentication (Completed)
- [x] Project Setup (Directory structure, FastAPI configuration, dependency setup)
- [x] Base Database Engine (SQLAlchemy 2.0 Async Session)
- [x] Security Layer (JWT token generation; bcrypt password hashing called directly -- Passlib was removed, see Stabilisation below)
- [x] Multi-Tenant Architecture Models (`Organization`, `User` with Tenant Isolation)
- [x] Authentication Router & Schemas (`/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/me`)
- [x] Health Check Endpoints (`/health`, `/health/ready`, `/health/live`)
- [x] Initial Architecture & API Contract Documentation

## Phase 2: Regulatory Authorities & Sources Registry (Completed)
- [x] Regulatory Authority Model (`RegulatoryAuthority`)
- [x] Regulatory Source Model (`RegulatorySource`) with connector types (RSS, API, HTML, Document, Web Service)
- [x] Ingestion Run Model (`IngestionRun`) to track source execution
- [x] API Schemas for Authorities, Sources, and Ingestion Runs
- [x] API Routers for Authorities (`/api/v1/regulatory/authorities`) and Sources (`/api/v1/regulatory/sources`)
- [x] Endpoints for CRUD operations on authorities and sources
- [x] Endpoints to trigger source runs and list run history
- [x] Tenant isolation: sources and authorities are not tied to a specific organization (they are global/configuration data)

## Phase 3: Document Ingestion & Processing (Completed)
- [x] Document Model (`RegulatoryDocument`) and Versioning Model (`RegulatoryVersion`)
- [x] Duplicate Detection via SHA-256
- [x] Manual Document Upload Endpoint (`/api/v1/regulatory/documents/upload`)
- [x] Document Upload Service with deduplication and storage abstraction
- [x] Document Processing Pipeline (parsing, versioning, text extraction, etc.)
- [x] Document Versioning Logic (automatically create new version on content change)
- [x] Background Processing for Document Pipeline
- [x] Text Extraction for PDF, DOCX, HTML, TXT
- [x] Document Status Endpoints (`/process`, `/status`)

## Phase 4: Regulatory Intelligence (AI Pipeline) (Completed)
- [x] AI Provider Abstraction (`AIProvider`) with Ollama and OpenAI implementations
- [x] Structured AI Output Schemas for document analysis (summary, changes, obligations)
- [x] AI Service to orchestrate document analysis with retry logic and validation
- [x] Intelligence Service to persist extracted changes and obligations
- [x] Document Analysis Endpoint (to be added to document processing flow)

## Phase 5: Portfolio Management (Completed)
- [x] Portfolio Models: Product, Market, Process, Control, Registration, ProductMarket
- [x] Portfolio Schemas for all models
- [x] Portfolio Routers for CRUD operations on all portfolio entities
- [x] Tenant isolation: all portfolio entities are scoped to organization_id
- [x] Seeded demo data for Asterion Medical Systems (organization, users, products, markets, processes, controls, registrations, authorities, sources)

## Phase 6: Impact Assessment & Delta Reports (Completed)
- [x] Impact Assessment, Impact Item, and Impact Report Models (`ImpactAssessment`, `ImpactItem`, `ImpactReport`)
- [x] Deterministic Matching Engine (`MatchingEngineService` + `app/matching/rules.py`) connecting Regulatory Changes/Obligations to Portfolio (Products, Markets, Processes, Controls, Registrations). Issues **no AI call**: an assessment is always produced even with every provider offline
- [x] Every impact item carries its `MatchType` signals and a JSON evidence payload naming the exact fields that matched
- [x] Impact scoring and confidence derived from the signals that actually fired (`SIGNAL_WEIGHTS`, `CONFIDENCE_BY_EVIDENCE_COUNT`); no hardcoded scores
- [x] Optional AI enrichment (`app/services/ai_enrichment.py`), off by default, bounded to one attempt, run via `BackgroundTasks` outside the request path, with explicit `AIEnrichmentStatus` (`DISABLED`/`SUCCESS`/`RATE_LIMITED`/`TIMEOUT`/`UNAVAILABLE`/`INVALID_RESPONSE`/`AUTH_ERROR`/`PROVIDER_ERROR`). A failure is never stored as an AI result
- [x] Versioned Impact Delta Report generation service (`ReportService`) distinguishing Fact, Source Evidence, System Interpretation, and Human Decision
- [x] REST API Routers for Impact Assessments (`/api/v1/impact/analyze`, `/api/v1/impact`, `/api/v1/impact/{id}`, `/api/v1/impact/{id}/items`, `/api/v1/impact/{id}/reanalyze`)
- [x] REST API Routers for Impact Delta Reports (`/api/v1/reports/generate`, `/api/v1/reports`, `/api/v1/reports/{id}`, `/api/v1/reports/{id}/versions`)
- [x] Test suite: deterministic chain, no-match path, AI-failure matrix (429/timeout/unavailable/auth/malformed/disabled), multi-tenant isolation, idempotency & versioning

## Stabilisation (pre-Phase 7)
- [x] SQLAlchemy mapper repaired: `Organization`/`User` referenced four models that did not exist, `RegulatoryChange.impact_assessments` had an asymmetric `back_populates`, and `ImpactItem.obligation` pointed at a missing attribute. Mapper configuration is lazy, so this only surfaced at the first ORM query -- every Phase 6 endpoint was dead. Guarded by `app/tests/test_models_registry.py`
- [x] Authentication migrated off Passlib to the `bcrypt` library directly. Passlib 1.7.4 is incompatible with bcrypt 5.x and broke `hash_password()` for every input. Stored format is unchanged (`$2b$12$...`), so existing hashes keep working; the temporary `bcrypt<5` pin was removed
- [x] `get_current_user` now rejects deactivated users, so revocation takes effect immediately instead of when the token expires
- [x] CORS-safe error handling (`app/core/errors.py`): unhandled exceptions are converted to a controlled 500 *inside* the CORS middleware, so the browser can read them. Previously they escaped to Starlette's `ServerErrorMiddleware`, which sits outside CORS, and surfaced in the frontend as `TypeError: Failed to fetch`
- [x] Request correlation: `X-Request-ID` on every response, honoured from the client if supplied, bound into structured logs, returned in the error body, and exposed to JavaScript via `expose_headers`
- [x] Consistent error envelope with a stable `error.code`, retaining FastAPI's `detail` for existing consumers. Stack traces, SQL and credentials stay server-side
- [x] `scripts/init_db.py` for schema creation, additive column sync and idempotent seeding; `--check` reports drift
- [x] Demo seed made idempotent per entity -- it previously returned early if the organization existed, leaving partially-seeded databases permanently empty
- [x] Tests enforce SQLite foreign keys so dangling references fail in tests rather than only in production on PostgreSQL

## Phase 7: Human Review & Actions (Completed)
- [x] `ImpactReview` completed: `organization_id` denormalised from the parent assessment so
  review queries are tenant-scoped without a join, plus `new_state` alongside `previous_state`
  so a row records where a decision led as well as where it came from
- [x] `Action` completed: `completed_at`, and `priority` promoted from a free-form `String(20)`
  to an `ActionPriority` enum
- [x] `ACTION_TRANSITIONS` as the single source of truth for the action state machine, with
  `COMPLETED` and `CANCELLED` terminal. The partial-update path goes through the same check,
  so it is not a back door around the machine
- [x] Reviews are append-only: a changed mind files a new row rather than rewriting an old
  one, and filing a decision moves the assessment in the same unit of work
- [x] Services scope every query to an organization; a cross-tenant id reads as 404, never 403
- [x] Tenant and reviewer identity taken from the access token, not the request body
- [x] REST API routers (`/api/v1/reviews`, `/api/v1/actions`)
- [x] Alembic revision `0002_phase7`, written to be safe on a populated database
- [x] Tests: model constraints, both services, the HTTP contract, state conflicts, tenant
  isolation, and identity spoofing attempts

## Migrations
- [x] Alembic environment added (`alembic.ini`, `migrations/`). The project had `alembic` in
  `requirements.txt` but no environment, so the schema had only ever been applied ad hoc --
  which is how the deployed database ended up missing columns the models had already grown
- [x] `0001_baseline` — the Phase 6 schema as deployed, for stamping an existing database
- [x] `0002_phase7` — the review and action changes
- [x] `0003_enrichment_not_null` — corrects real drift found by `alembic check` against the
  deployed database: `impact_assessments.ai_enrichment_status` was nullable there despite the
  model declaring it NOT NULL, because it had been added by an ad-hoc script

## Seeds
- [x] Registrations added. The seed imported `Registration` and never created one, which left
  `registration_evidence()` unable to fire: with an empty table, an assessment could never show
  a product's market authorisation as exposed

## Phase 8: Evidence & Audit Trail (Completed)

**No migration was required.** The `evidence` and `audit_events` tables were already
defined and migrated by the Phase 6 baseline; what was missing was everything above them.
Phase 8 is therefore additive service, schema and router code only.

### Audit trail
- [x] `AuditService.record()` adds an event to the **caller's** session and deliberately
  does not commit. That single decision is what makes the trail trustworthy: a change and
  the event describing it now succeed or fail together, so a refused action transition
  cannot leave behind an event claiming it happened. Pinned by a test that rolls back and
  finds nothing
- [x] Emission from inside the transactions that make each change. For the matching
  engine, the report service and the document service this meant reaching into the
  service, because all three commit internally and recording in the router would have put
  the event in a second transaction
- [x] Events written: `USER_SIGNED_IN`, `DOCUMENT_UPLOADED`, `DOCUMENT_PROCESSED`,
  `IMPACT_ASSESSMENT_CREATED`, `IMPACT_ASSESSMENT_REANALYZED`, `REPORT_GENERATED`,
  `REVIEW_FILED`, `ACTION_CREATED`, `ACTION_UPDATED`, `ACTION_STATUS_CHANGED`,
  `EVIDENCE_ATTACHED`
- [x] `event_type` stays a free `String(100)` on the column *and* the wire rather than
  becoming an enum, so an event written by an older or newer revision still reads back
  instead of failing serialisation. `GET /audit/event-types` serves the vocabulary so a
  client can filter without hardcoding a list that would drift
- [x] Read-only over HTTP: `POST`/`PATCH`/`DELETE` are 405. The only way to add an event
  is to make the change it describes
- [x] Deliberately not recorded: a failed sign-in (that belongs in the security log, and
  writing it would mean writing rows for a caller who never authenticated); a refused
  change; a no-op (re-sent status, duplicate upload, idempotent re-analysis); and free
  text or secrets — an edit records the field *names* that changed, a review records
  *whether* a note was left rather than the note
- [x] `actor_id` is threaded through the action service and taken from the access token in
  the router, never the request body. It is distinct from `owner_id`: one is who acted,
  the other is who was asked to do the work
- [x] Tests: recording, filters, the rollback property, tenant isolation at both the
  service and HTTP layers, the 405s, and that every emitted type is a declared one

### Evidence
- [x] Upload (multipart), list, read and download, scoped to an organization
- [x] Evidence attaches to an **action and nothing else**, because that is what the table
  supports: an `action_id` with no generic `entity_type`/`entity_id` pair. It reaches the
  rest of the chain through the action — evidence → action → impact item → assessment →
  regulatory change → document. There is **no `evidence_type`**; no such column or enum
  exists anywhere in the repo
- [x] `storage_key` is never serialised. It is an internal filesystem path with no
  legitimate client use; the download endpoint resolves it server-side after checking the
  tenant. A test asserts it is absent from every response and present in the row
- [x] Ownership of the action is checked **before** the file is stored, so a request
  naming another tenant's action writes nothing at all
- [x] Not deduplicated by `sha256`, unlike a regulatory document: the same file may
  legitimately substantiate two actions, and refusing the second would lose the fact that
  it was offered for both. The hash is an integrity anchor, not a uniqueness constraint
- [x] A record whose stored file has gone is `410`, not `404` — a `404` would claim the
  evidence was never filed, which is a different and more alarming thing to tell an
  auditor

### Regulatory intelligence (read-only)
- [x] `GET /regulatory/changes/`, `/changes/{id}`, `/changes/{id}/obligations`,
  `/obligations/`, `/obligations/{id}`. These close a real gap: an impact assessment
  carried a `regulatory_change_id` that no endpoint could resolve, so a client could show
  the id and the engine's summary but could not link through to the change itself or list
  the obligations behind a match
- [x] **Tenancy runs through the document.** Neither table has an `organization_id`, so
  every query joins `regulatory_documents` and filters on its `organization_id`. Without
  that join these endpoints would hand every tenant's extracted intelligence to every
  other tenant, and nothing else in the suite would have caught it — hence a test that
  gives a second tenant a change of its own and asserts neither can see the other's
- [x] Read-only, 405 on writes. The pipeline owns these rows; hand-editing an extracted
  obligation would destroy the provenance that makes it worth anything

A naming trap, still worth stating: the `Evidence` in `app/matching/rules.py` is an
unrelated local dataclass carrying match provenance, and `ImpactItemResponse.evidence` is
a JSON-encoded string of match signals. Neither is the `evidence` table.

## Next Phase
Nothing is queued. The served surface is 54 paths and the suite is 173 tests.
