# PARIVART Backend

Enterprise Regulatory Change Intelligence platform backend.

## Technology Stack
- **Language**: Python 3.14
- **Framework**: FastAPI 0.141
- **Database**: PostgreSQL with SQLAlchemy 2.1 Async
- **ORM Migrations**: Alembic
- **Security**: JWT (python-jose), Passlib (bcrypt)
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

# Run uvicorn directly for development
uvicorn app.main:app --reload
```

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
