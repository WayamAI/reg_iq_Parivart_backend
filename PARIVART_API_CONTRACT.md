# PARIVART API Contract

This document establishes the canonical API contract between the PARIVART FastAPI Backend and the PARIVART Frontend (`Niyo360`).

## Base URL
`/api/v1`

## Standard Response Envelope
All successful responses return JSON. List endpoints follow:
```json
{
  "items": [],
  "page": 1,
  "page_size": 25,
  "total": 0,
  "total_pages": 0
}
```

Standard Error Envelope:
```json
{
  "error": {
    "code": "ERROR_CODE_STRING",
    "message": "Human readable description",
    "details": {}
  }
}
```

---

## Endpoints Summary

### 1. Authentication (`/api/v1/auth`)
- `POST /api/v1/auth/register` — Register a new user/organization
- `POST /api/v1/auth/login` — Obtain JWT access token
- `POST /api/v1/auth/logout` — Revoke session
- `GET /api/v1/auth/me` — Current user profile

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
