# PARIVART API Contract

This document establishes the canonical API contract between the PARIVART FastAPI Backend and the PARIVART Frontend.

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

### 1. Authentication (`/api/auth`)
- `POST /api/auth/register` — Register a new user/organization
- `POST /api/auth/login` — Obtain JWT access token
- `POST /api/auth/logout` — Revoke session
- `GET /api/auth/me` — Current user profile

### 2. Dashboard (`/api/dashboard`)
- `GET /api/dashboard` — Real derived metrics (changes, potentially affected, high impact, open actions, overdue, source health, recent activity)

### 3. Regulatory Authorities & Sources (`/api/regulatory`)
- `GET /api/regulatory/authorities`
- `POST /api/regulatory/authorities`
- `GET /api/regulatory/sources`
- `POST /api/regulatory/sources`
- `POST /api/regulatory/sources/{id}/run`
- `GET /api/regulatory/sources/{id}/runs`

### 4. Documents (`/api/regulatory/documents`)
- `GET /api/regulatory/documents`
- `POST /api/regulatory/documents/upload` (Supports PDF, DOCX, HTML, TXT)
- `GET /api/regulatory/documents/{id}`
- `POST /api/regulatory/documents/{id}/process`
- `GET /api/regulatory/documents/{id}/status`

### 5. Regulatory Intelligence (`/api/regulatory/changes`, `/api/regulatory/obligations`)
- `GET /api/regulatory/changes`
- `GET /api/regulatory/changes/{id}`
- `GET /api/regulatory/obligations`

### 6. Portfolio (`/api/portfolio`)
- `GET /api/portfolio/products` & `POST`
- `GET /api/portfolio/markets` & `POST`
- `GET /api/portfolio/processes` & `POST`
- `GET /api/portfolio/controls` & `POST`

### 7. Impact Assessments (`/api/impact`)
- `GET /api/impact`
- `GET /api/impact/{id}`
- `POST /api/impact/{id}/analyze`
- `POST /api/impact/{id}/review`

### 8. Reports (`/api/reports`)
- `GET /api/reports`
- `POST /api/reports/generate`
- `GET /api/reports/{id}/download`

### 9. Actions (`/api/actions`)
- `GET /api/actions` & `POST`
- `PATCH /api/actions/{id}`
- `POST /api/actions/{id}/complete`

### 10. Evidence & Audit (`/api/evidence`, `/api/audit`)
- `POST /api/evidence/upload`
- `GET /api/audit`
