from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from company_lens import __version__
from company_lens.api.errors import install_error_handlers
from company_lens.api.middleware import BodySizeLimitMiddleware
from company_lens.api.v1.catalog import router as catalog_router
from company_lens.api.v1.health import router as health_router
from company_lens.api.v1.research import router as research_router
from company_lens.config import get_settings
from company_lens.db.session import build_session_factory
from company_lens.observability.correlation import CorrelationIdMiddleware
from company_lens.observability.logging import configure_logging
from company_lens.research.repository import ResearchRunRepository


def create_app(*, research_repository: ResearchRunRepository | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = None
    if research_repository is None:
        session_factory = build_session_factory(settings.database_url)
        research_repository = ResearchRunRepository(session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.research_repository = research_repository
        try:
            yield
        finally:
            if session_factory is not None:
                engine = session_factory.kw.get("bind")
                if isinstance(engine, Engine):
                    engine.dispose()

    app = FastAPI(
        title="CompanyLens API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.api_max_body_bytes)
    app.add_middleware(CorrelationIdMiddleware)
    app.state.research_repository = research_repository
    install_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(research_router, prefix="/api/v1")
    app.include_router(catalog_router, prefix="/api/v1")
    return app
