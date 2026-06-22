from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from company_lens.observability.correlation import CORRELATION_ID_STATE_KEY
from company_lens.research.repository import (
    ActiveResearchRunError,
    RateLimitExceededError,
    ResearchRunNotFoundError,
)
from company_lens.research.schemas import PublicErrorDetail, PublicErrorResponse


class PublicApiError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PublicApiError)
    def public_error(request: Request, exc: PublicApiError) -> JSONResponse:
        return _response(request, exc.status_code, exc.code, str(exc))

    @app.exception_handler(ResearchRunNotFoundError)
    def not_found(request: Request, exc: ResearchRunNotFoundError) -> JSONResponse:
        return _response(request, status.HTTP_404_NOT_FOUND, "research_run_not_found", str(exc))

    @app.exception_handler(ActiveResearchRunError)
    def active_run(request: Request, exc: ActiveResearchRunError) -> JSONResponse:
        return _response(request, status.HTTP_409_CONFLICT, "research_session_busy", str(exc))

    @app.exception_handler(RateLimitExceededError)
    def rate_limited(request: Request, exc: RateLimitExceededError) -> JSONResponse:
        response = _response(
            request, status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded", str(exc)
        )
        response.headers["Retry-After"] = "60"
        return response

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        return _response(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "request_validation_failed",
            "The request did not match the API contract.",
        )

    @app.exception_handler(Exception)
    def internal_error(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "The request could not be completed.",
        )


def public_error_response(
    request: Request, status_code: int, code: str, message: str
) -> JSONResponse:
    return _response(request, status_code, code, message)


def _response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    payload = PublicErrorResponse(
        error=PublicErrorDetail(
            code=code,
            message=message,
            correlation_id=getattr(request.state, CORRELATION_ID_STATE_KEY, None),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
