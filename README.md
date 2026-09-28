# PARIVART Backend

Enterprise Regulatory Change Intelligence platform backend.

## Technology Stack
- **Language**: Python 3.14
- **Framework**: FastAPI 0.141
- **Database**: PostgreSQL with SQLAlchemy 2.1 Async
- **ORM Migrations**: Alembic
- **Security**: JWT (python-jose), bcrypt (used directly, not via Passlib)
- **Validation**: Pydantic v2

## Quick Start

```bash
# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL and JWT_SECRET

# Create tables, add any missing columns, and seed demo data (idempotent)
python -m scripts.init_db

# Run uvicorn directly for development
uvicorn app.main:app --reload --port 8010
```

## Database

There is no Alembic environment yet, so the schema is applied with `scripts/init_db.py`:

```bash
python -m scripts.init_db            # create tables + add missing columns + seed
python -m scripts.init_db --no-seed  # schema only
python -m scripts.init_db --check    # report drift, exit non-zero if any (CI-friendly)
```

It is additive only -- it never drops or alters existing columns. Anything beyond adding a
nullable column needs a real migration.

## Error contract

Every error response carries an `X-Request-ID` header and a JSON body of the form:

```json
{
  "error": { "code": "INTERNAL_SERVER_ERROR", "message": "...", "request_id": "..." },
  "detail": "..."
}
```

`detail` is retained for backwards compatibility; `error.code` is the stable value clients
should switch on. Unhandled exceptions are converted to a 500 *inside* the CORS middleware,
so the browser can always read them -- a failed API call is distinguishable from an
unreachable backend (which produces no HTTP response at all). `/health` never touches the
database or an AI provider, so it stays a reliable reachability probe.

## API Documentation

Visit `/docs` or `/redoc` when running the server to view the interactive Swagger UI.

## Project Structure
```
app/
├── main.py
├── core/           # Config, Security, Logging, Exceptions
├── db/             # Database connections and dependencies
├── models/         # SQLAlchemy ORM models
├── api/
│   ├── dependencies/ # Auth and utility dependencies
│   ├── routers/   # API endpoints (auth, regulatory, portfolio, etc.)
│   └── schemas/   # Pydantic request/response models
└── ...
```

## Phases
1. [x] Project Setup & Authentication
2. Regulatory Authorities & Sources Registry
3. Document Ingestion & Processing
4. Regulatory Intelligence (AI pipeline)
5. Portfolio & Matching Engine
6. Impact Assessment & Reports
7. Execution, Evidence & Audit

## Branches
- `feature/az-ps-max-context-population` - Main development branch
