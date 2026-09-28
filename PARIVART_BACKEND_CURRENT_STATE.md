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

## Next Phase
- **Phase 7: Execution, Evidence & Audit** — models only so far (`app/models/governance.py`:
  `Action`, `Evidence`, `AuditEvent`, `ImpactReview`). They exist because `Organization` and
  `User` already declared relationships to them; no routers, schemas or seed data yet.
