from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from company_lens_reranker.schemas import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    ReadyResponse,
    RerankRequest,
    RerankResponse,
)
from company_lens_reranker.scoring import CrossEncoderScorer, ScoringError, build_scorer


def create_app(*, scorer: CrossEncoderScorer | None = None) -> FastAPI:
    app = FastAPI(title="CompanyLens Internal Reranker Service", version="0.1.0")
    app.state.scorer = scorer or build_scorer()

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            "Rerank request is invalid.",
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/ready", response_model=ReadyResponse)
    def ready() -> ReadyResponse | JSONResponse:
        try:
            _scorer(app).ensure_ready()
        except Exception:
            return _error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "model_not_ready",
                "Reranker model is not ready.",
            )
        return ReadyResponse(model=_scorer(app).model_name)

    @app.post("/rerank", response_model=RerankResponse)
    def rerank(request: RerankRequest) -> RerankResponse | JSONResponse:
        try:
            scores = _scorer(app).score(query=request.query, items=request.items)
        except ScoringError:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "scoring_failed",
                "Reranker scoring failed.",
            )
        except Exception:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "scoring_failed",
                "Reranker scoring failed.",
            )
        return RerankResponse(model=_scorer(app).model_name, scores=scores)

    return app


def _scorer(app: FastAPI) -> CrossEncoderScorer:
    return app.state.scorer


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


app = create_app()
