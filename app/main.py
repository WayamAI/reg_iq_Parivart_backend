import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProviderFactory
from app.ai.startup import register_configured_providers, shutdown_registered_providers
from app.api.routers import (
    auth,
    authorities_router,
    sources_router,
    regulatory_documents,
    products_router,
    markets_router,
    processes_router,
    controls_router,
    registrations_router,
    impact_router,
    reports_router,
    reviews_router,
    actions_router,
    audit_router,
    evidence_router,
    intelligence_router,
)
from app.core.config import settings
from app.core.errors import (
    REQUEST_ID_HEADER,
    ExceptionHandlingMiddleware,
    RequestContextMiddleware,
    register_exception_handlers,
)
from app.db.database import get_db

logger = structlog.get_logger()

app = FastAPI(
    title="PARIVART Backend API",
    description="Enterprise Regulatory Change Intelligence platform",
    version="0.1.0",
)

# --- Middleware ------------------------------------------------------------------------
# Order matters. add_middleware() prepends, so the LAST one added is the OUTERMOST.
# The resulting stack is:
#
#     CORSMiddleware                 <- outermost: decorates everything below it
#       -> RequestContextMiddleware  <- assigns X-Request-ID, binds it into the logs
#         -> ExceptionHandlingMiddleware
#           -> router
#
# ExceptionHandlingMiddleware must sit *inside* CORSMiddleware. Starlette's built-in
# ServerErrorMiddleware is outside it, which is precisely why unhandled 500s used to come
# back without Access-Control-Allow-Origin and surfaced in the browser as
# "TypeError: Failed to fetch".
app.add_middleware(ExceptionHandlingMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser hides the correlation id from JavaScript, so the frontend
    # cannot show or report the request id for a failed call.
    expose_headers=[REQUEST_ID_HEADER],
)

# Give deliberate HTTP errors (401/403/404/409/422/...) the same envelope and request id.
register_exception_handlers(app)


@app.on_event("startup")
async def _register_ai_providers() -> None:
    """
    Populate AIProviderFactory from current configuration.

    Without this, nothing ever called register_provider outside tests, so the registry
    was empty in every real run and AI_PROVIDER could never resolve -- see
    app/ai/startup.py for exactly which providers are registered and under what
    conditions. Never raises: a misconfigured or disabled provider is logged and
    skipped, not a startup failure.
    """
    register_configured_providers()


@app.on_event("shutdown")
async def _shutdown_ai_providers() -> None:
    await shutdown_registered_providers()

# --- Routers ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/v1")
app.include_router(authorities_router, prefix="/api/v1/regulatory")
app.include_router(sources_router, prefix="/api/v1/regulatory")
app.include_router(regulatory_documents.router, prefix="/api/v1/regulatory")
app.include_router(intelligence_router, prefix="/api/v1/regulatory")
app.include_router(products_router, prefix="/api/v1/portfolio")
app.include_router(markets_router, prefix="/api/v1/portfolio")
app.include_router(processes_router, prefix="/api/v1/portfolio")
app.include_router(controls_router, prefix="/api/v1/portfolio")
app.include_router(registrations_router, prefix="/api/v1/portfolio")
app.include_router(impact_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(reviews_router, prefix="/api/v1")
app.include_router(actions_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(evidence_router, prefix="/api/v1")


# --- Health ----------------------------------------------------------------------------
# Deliberately cheap: no database round-trip, no AI provider call. These exist so a client
# can tell "backend unreachable" from "backend reachable but the request failed", which
# means they must never fail for a reason unrelated to the process being up.
@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy"}


@app.get("/health/ready", tags=["Health"])
def readiness_check():
    return {"status": "ready"}


@app.get("/health/live", tags=["Health"])
def liveness_check():
    return {"status": "live"}


# --- Status -----------------------------------------------------------------------------
# Unlike /health, this one *does* touch its dependencies: it is the endpoint the frontend
# and an operator use to tell "backend up but database degraded" from "backend up and
# healthy". It therefore always answers 200 -- a degraded dependency is reported in the
# body, never as an HTTP error, because a non-200 here would be indistinguishable from the
# process being down.
#
# No secret ever enters this payload: no API key, no JWT secret, no database URL. The AI
# block is read from configuration and the provider registry only -- it never calls a
# provider, because a demo must not hang for AI_TIMEOUT_SECONDS on a status probe.
@app.get("/status", tags=["Health"])
async def status_check(db: AsyncSession = Depends(get_db)):
    database = {"status": "up", "error": None}
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure is "down", never a 500
        logger.warning("status_database_check_failed", error=str(exc))
        database = {"status": "down", "error": str(exc)}

    return {
        "app": app.title,
        "version": app.version,
        "environment": settings.APP_ENV,
        "database": database,
        "ai": {
            "enabled": settings.AI_ENRICHMENT_ENABLED,
            "provider": settings.AI_PROVIDER,
            "model": settings.AI_MODEL,
            # False means no provider was registered in this deployment, so enrichment can
            # only ever record UNAVAILABLE and every assessment stays fully deterministic.
            "provider_registered": settings.AI_PROVIDER in AIProviderFactory._providers,
        },
    }
