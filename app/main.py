from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routers import auth, authorities_router, sources_router, regulatory_documents

app = FastAPI(
    title="PARIVART Backend API",
    description="Enterprise Regulatory Change Intelligence platform",
    version="0.1.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(authorities_router, prefix="/api/v1/regulatory")
app.include_router(sources_router, prefix="/api/v1/regulatory")
app.include_router(regulatory_documents.router, prefix="/api/v1/regulatory")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/health/ready")
def readiness_check():
    return {"status": "ready"}

@app.get("/health/live")
def liveness_check():
    return {"status": "live"}
