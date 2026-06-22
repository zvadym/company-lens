from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from company_lens.api.dependencies import (
    Principal,
    get_api_settings,
    get_principal,
    get_research_repository,
)
from company_lens.api.errors import PublicApiError
from company_lens.config import Settings
from company_lens.research.repository import ResearchRunRepository
from company_lens.research.schemas import (
    CompaniesResponse,
    FeedbackRequest,
    FeedbackResponse,
)

router = APIRouter(tags=["catalog"])


@router.get("/companies", response_model=CompaniesResponse)
def companies(
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
) -> CompaniesResponse:
    return repository.companies()


@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def feedback(
    payload: FeedbackRequest,
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
    settings: Annotated[Settings, Depends(get_api_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> FeedbackResponse:
    if payload.comment is not None and len(payload.comment) > settings.feedback_comment_max_chars:
        raise PublicApiError(
            413,
            "feedback_comment_too_large",
            "Feedback comment exceeds the configured size limit.",
        )
    repository.consume_rate_limit(
        principal.subject,
        "feedback:create",
        limit=settings.feedback_rate_limit_per_minute,
        window_seconds=60,
    )
    return repository.create_feedback(payload)
