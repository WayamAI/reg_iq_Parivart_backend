# PARIVART Architecture

## Layered Architecture
- **API (Routers/Schemas/Deps)**: FastAPI request handling, validation, and serialization (Pydantic v2).
- **Core**: Global services (security, database engine, logging, base exceptions).
- **Services (Domain Logic)**: Layer for complex business rules (Regulatory, Ingestion, Portfolio Matching, Impact Engine).
- **Models**: SQLAlchemy 2.0 ORM base classes.
- **Repositories**: Database access abstraction (data access layer).
- **Connectors**: Pluggable source ingestion (RSS, Web API, HTML).
- **AI**: Configurable Provider Abstraction (Ollama, OpenAI) with Pydantic structured output validation.
- **Workers**: Async background job processing.
- **Storage**: Abstracted local/object storage.

## Key Design Principles
1. **Tenant Isolation**: Every database operation involving an organization-owned entity is scoped to the `organization_id`.
2. **Deterministic Processing**: Document versions are hashed (`SHA-256`) to ensure idempotency.
3. **Structured AI**: AI intelligence (Obligations, Changes) uses enforced Pydantic schemas.
4. **Auditability**: All state-changing events (review, action update, ingestion run) are recorded in the append-only `AuditEvent` log.
5. **Observability**: Consistent structured logging with `request_id`, `organization_id`, and `job_id`.
6. **Background Execution**: Long-running parsing/AI intelligence operations are asynchronous to ensure low latency for HTTP API responses.
