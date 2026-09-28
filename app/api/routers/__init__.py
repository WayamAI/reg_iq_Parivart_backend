from .auth import router as auth_router
from .regulatory_authorities import router as authorities_router
from .regulatory_sources import router as sources_router
from .regulatory_documents import router as documents_router
from .portfolio_products import router as products_router
from .portfolio_markets import router as markets_router
from .portfolio_processes import router as processes_router
from .portfolio_controls import router as controls_router
from .portfolio_registrations import router as registrations_router
from .impact import router as impact_router
from .reports import router as reports_router

__all__ = [
    "auth_router",
    "authorities_router",
    "sources_router",
    "documents_router",
    "products_router",
    "markets_router",
    "processes_router",
    "controls_router",
    "registrations_router",
    "impact_router",
    "reports_router",
]