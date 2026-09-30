from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
)
from app.core.config import settings
from app.core.errors import (
    REQUEST_ID_HEADER,
    ExceptionHandlingMiddleware,
    RequestContextMiddleware,
    register_exception_handlers,
)

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

# --- Routers ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/v1")
app.include_router(authorities_router, prefix="/api/v1/regulatory")
app.include_router(sources_router, prefix="/api/v1/regulatory")
app.include_router(regulatory_documents.router, prefix="/api/v1/regulatory")
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
