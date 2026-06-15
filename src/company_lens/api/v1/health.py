from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from company_lens import __version__
from company_lens.config import Settings, get_settings
from company_lens.db.health import check_database
from company_lens.observability.correlation import CORRELATION_ID_STATE_KEY
from company_lens.schemas.health import ComponentHealth, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    database = check_database(settings.database_url)
    overall_status: Literal["ok", "degraded"] = "ok" if database.status == "ok" else "degraded"
    payload = HealthResponse(
        status=overall_status,
        service="company-lens-api",
        version=__version__,
        environment=settings.environment,
        correlation_id=getattr(request.state, CORRELATION_ID_STATE_KEY, None),
        database=ComponentHealth(
            status=database.status,
            latency_ms=database.latency_ms,
            detail=database.detail,
        ),
    )
    http_status = (
        status.HTTP_200_OK if overall_status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
