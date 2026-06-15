from __future__ import annotations

from fastapi import FastAPI

from company_lens import __version__
from company_lens.api.v1.health import router as health_router
from company_lens.config import get_settings
from company_lens.observability.correlation import CorrelationIdMiddleware
from company_lens.observability.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CompanyLens API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(health_router, prefix="/api/v1")
    return app
