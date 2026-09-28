# PARIVART Phase 6 Design Document

This document specifies the architecture and implementation details for Phase 6 of the PARIVART backend: Portfolio Matching Engine, Impact Assessment, and Impact Delta Reports.

## 1. Domain Models (`app/models/impact.py`)

### Enums
- `ImpactAssessmentStatus`: `PENDING`, `ANALYZING`, `COMPLETED`, `FAILED`, `REQUIRES_REVIEW`, `REVIEWED`
- `ImpactLevel`: `NO_MATCH`, `LOW`, `MEDIUM`, `HIGH`, `POTENTIALLY_AFFECTED`, `REQUIRES_REVIEW`
- `EntityType`: `PRODUCT`, `MARKET`, `PROCESS`, `CONTROL`, `REGISTRATION`
- `MatchType`: `JURISDICTION_MATCH`, `PRODUCT_CATEGORY_MATCH`, `PRODUCT_KEYWORD_MATCH`, `MARKET_MATCH`, `PROCESS_MATCH`, `CONTROL_MATCH`, `REGISTRATION_MATCH`, `SEMANTIC_MATCH`, `AI_REVIEW`
- `ImpactReportStatus`: `DRAFT`, `GENERATED`, `UNDER_REVIEW`, `REVIEWED`, `ARCHIVED`
- `AIEnrichmentStatus`: `DISABLED`, `SUCCESS`, `RATE_LIMITED`, `TIMEOUT`, `UNAVAILABLE`,
  `INVALID_RESPONSE`, `AUTH_ERROR`, `PROVIDER_ERROR`

### Tables
1. **`impact_assessments`**
   - `id` (PK, String 36)
   - `organization_id` (FK to organizations, indexed)
   - `regulatory_change_id` (FK to regulatory_changes, indexed)
   - `status` (Enum)
   - `overall_impact_level` (Enum)
   - `overall_confidence` (Numeric 3,2)
   - `summary` (Text)
   - `analysis_version` (Integer, default 1)
   - `engine_version` (String 50)
   - `ai_model` (String 100, NULL unless enrichment succeeded)
   - `prompt_version` (String 100, NULL unless enrichment succeeded)
   - `ai_enrichment_status` (Enum `AIEnrichmentStatus`, NOT NULL, default `DISABLED`)
   - `ai_enrichment_error` (Text, nullable)
   - `ai_narrative` (Text, nullable)
   - `created_at`, `updated_at`

2. **`impact_items`**
   - `id` (PK, String 36)
   - `impact_assessment_id` (FK to impact_assessments, indexed)
   - `obligation_id` (FK to regulatory_obligations, nullable, indexed)
   - `entity_type` (Enum)
   - `entity_id` (String 36, indexed)
   - `impact_level` (Enum)
   - `confidence` (Numeric 3,2)
   - `match_score` (Numeric 3,2)
   - `reason` (Text)
   - `match_types` (String 500, comma-separated `MatchType` values that fired)
   - `evidence` (Text / JSON: entity label, match types, and every signal with the
     concrete regulatory and portfolio field values that matched)
   - `status` (String 50)
   - `created_at`, `updated_at`

3. **`impact_reports`**
   - `id` (PK, String 36)
   - `organization_id` (FK to organizations, indexed)
   - `impact_assessment_id` (FK to impact_assessments, indexed)
   - `regulatory_change_id` (FK to regulatory_changes, indexed)
   - `title` (String 255)
   - `summary` (Text)
   - `status` (Enum)
   - `version` (Integer, default 1)
   - `report_data` (Text / JSON storing structured Fact, Source Evidence, System Interpretation, Human Decision)
   - `created_at`, `updated_at`

---

## 2. Matching Engine Architecture

Split in two, so the rules can be reasoned about and tested without a database:

- `app/matching/rules.py` — pure rules, weights and evidence types. No DB, no network, no AI.
- `app/matching/engine.py` — loads the tenant's data and applies the rules.

`ENGINE_VERSION = "deterministic-v2"`. The engine issues **no AI call at any point**, which
is what makes `AI unavailable -> PARIVART still works` true rather than aspirational.

Stages:

1. **Market resolution** (`rules.resolve_markets`) — link the publishing authority/document
   to the organization's own markets on three mutually independent axes:

   | Axis | Regulatory side | Portfolio side |
   |---|---|---|
   | `authority_short_name` | `authority.short_name` | `market.regulatory_jurisdiction` |
   | `jurisdiction` | `authority`/`document`.`jurisdiction` | `market.name`, `market.regulatory_jurisdiction` |
   | `country` | `authority`/`document`.`country` | `market.country` |

   Comparison is case-insensitive and NULL-safe. A market with no matching axis is not a
   match. **There is no fallback** — if nothing links the change to the portfolio, the
   result is `NO_MATCH` with zero items.
2. **Product candidates** — only products linked to a resolved market via `ProductMarket`
   (the join is scoped through `Product.organization_id`, so it never reads another tenant).
3. **Category & keyword match** (`rules.product_term_evidence`) — `product.category`,
   `sub_category` and `keywords` searched against the change/obligation text. Terms shorter
   than `MIN_KEYWORD_LENGTH` (4) are ignored as coincidental.
4. **Process alignment** (`rules.process_evidence`) — only via the explicit
   `OBLIGATION_CATEGORY_TO_PROCESS_NAMES` table, and only when an obligation in a mapped
   category is actually present. No obligation, no process item.
5. **Control alignment** (`rules.control_evidence`) — via
   `OBLIGATION_CATEGORY_TO_CONTROL_CATEGORIES`, or because the control's
   `product_id`/`process_id` points at an entity that already matched.
6. **Registration exposure** (`rules.registration_evidence`) — the registration was granted
   by the publishing authority, or sits in a resolved market.
7. **Scoring** — `match_score` is the sum of `SIGNAL_WEIGHTS` for the `MatchType`s that
   fired, clamped to `[0, 1]`. `confidence` comes from `CONFIDENCE_BY_EVIDENCE_COUNT`: how
   many independent axes fired, not how severe the impact is. `impact_level` is a threshold
   over `match_score` (`IMPACT_LEVEL_THRESHOLDS`); a weak-signal-only match reports
   `POTENTIALLY_AFFECTED` rather than asserting a level. No score is hardcoded per item.

Each `ImpactItem` stores its `match_types` plus a JSON `evidence` payload listing every
signal with the concrete regulatory and portfolio field values that matched.

---

## 2b. Optional AI Enrichment (`app/services/ai_enrichment.py`)

```
deterministic assessment  ->  always available
optional AI enrichment    ->  only when available
```

- Off by default (`AI_ENRICHMENT_ENABLED=false`). When on, it is scheduled via FastAPI
  `BackgroundTasks` **after** the assessment is committed, so no request ever waits on a
  provider.
- Bounded: `AI_MAX_ATTEMPTS` defaults to 1, passed down into the provider's own retry loop.
  A `429`'s `Retry-After` is recorded for an operator; it is never slept on or retried.
- Every outcome is an explicit `AIEnrichmentStatus`: `DISABLED`, `SUCCESS`, `RATE_LIMITED`,
  `TIMEOUT`, `UNAVAILABLE`, `INVALID_RESPONSE`, `AUTH_ERROR`, `PROVIDER_ERROR`.
- Enrichment may only add `ai_narrative` (plus `ai_model`/`prompt_version`). It never
  touches items, `overall_impact_level` or `overall_confidence`. On anything other than
  `SUCCESS` those AI fields stay `NULL`, so a failure can never read as an AI result.

---

## 3. API Endpoints

All require authentication and are scoped to the caller's organization. A cross-tenant id
returns 404, not 403.

- **Impact Assessments**:
  - `POST /api/v1/impact/analyze`
  - `GET /api/v1/impact/`
  - `GET /api/v1/impact/{assessment_id}`
  - `GET /api/v1/impact/{assessment_id}/items`
  - `POST /api/v1/impact/{assessment_id}/reanalyze`

- **Impact Delta Reports**:
  - `POST /api/v1/reports/generate`
  - `GET /api/v1/reports/`
  - `GET /api/v1/reports/{report_id}`
  - `GET /api/v1/reports/{report_id}/versions`

Filtering impacts by change or by portfolio entity is not implemented; use
`GET /api/v1/impact/?regulatory_change_id=...` for the change case.

---

## 4. Impact Delta Report Structure

`report_data` is JSON with six sections, tracing the chain end to end:

| Section | Answers |
|---|---|
| `FACT` | WHAT CHANGED — publication facts, authority, jurisdiction, dates, sha256 |
| `SOURCE_EVIDENCE` | the citable extract: change summary/type/section, previous vs new text |
| `RESULTING_OBLIGATIONS` | WHAT OBLIGATION RESULTED — text, category, applicability, source section |
| `SYSTEM_INTERPRETATION` | WHAT IS AFFECTED and WHY — entities resolved to names, with per-item `match_types` and evidence |
| `AI_ENRICHMENT` | whether any AI contributed, and its status if not |
| `HUMAN_DECISION` | WHAT ACTION MAY BE REQUIRED — derived from matched obligation categories only |

Undeterminable facts are `UNKNOWN`; a section with nothing to say is `UNASSESSED` with an
empty action list. No business impact is invented.
