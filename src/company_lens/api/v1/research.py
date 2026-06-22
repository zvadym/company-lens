from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import StreamingResponse

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
    PublicErrorResponse,
    ResearchAccepted,
    ResearchRunResponse,
    ResearchSourcesResponse,
    StartResearchRequest,
)

router = APIRouter(prefix="/research", tags=["research"])


@router.post(
    "",
    response_model=ResearchAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: {"model": PublicErrorResponse}, 429: {"model": PublicErrorResponse}},
)
def start_research(
    payload: StartResearchRequest,
    request: Request,
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
    settings: Annotated[Settings, Depends(get_api_settings)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> ResearchAccepted:
    if len(payload.question) > settings.research_question_max_chars:
        raise PublicApiError(
            413,
            "research_question_too_large",
            "Research question exceeds the configured size limit.",
        )
    repository.consume_rate_limit(
        principal.subject,
        "research:start",
        limit=settings.research_start_rate_limit_per_minute,
        window_seconds=60,
    )
    session_id = payload.session_id or f"session-{uuid.uuid4()}"
    run = repository.enqueue(
        payload,
        session_id=session_id,
        timeout=timedelta(seconds=settings.research_run_timeout_seconds),
    )
    base = str(request.base_url).rstrip("/")
    path = f"/api/v1/research/{run.id}"
    return ResearchAccepted(
        run_id=run.id,
        session_id=run.session_id,
        run_url=f"{base}{path}",
        events_url=f"{base}{path}/events",
        sources_url=f"{base}{path}/sources",
    )


@router.get("/{run_id}", response_model=ResearchRunResponse)
def get_research(
    run_id: uuid.UUID,
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
) -> ResearchRunResponse:
    return repository.response(run_id)


@router.delete("/{run_id}", response_model=ResearchRunResponse)
def cancel_research(
    run_id: uuid.UUID,
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
) -> ResearchRunResponse:
    return repository.request_cancellation(run_id)


@router.get("/{run_id}/sources", response_model=ResearchSourcesResponse)
def get_sources(
    run_id: uuid.UUID,
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
) -> ResearchSourcesResponse:
    return repository.sources(run_id)


@router.get(
    "/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Versioned research execution event stream.",
        }
    },
)
def stream_events(
    run_id: uuid.UUID,
    repository: Annotated[ResearchRunRepository, Depends(get_research_repository)],
    settings: Annotated[Settings, Depends(get_api_settings)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    try:
        cursor = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        raise PublicApiError(
            400, "invalid_event_cursor", "Last-Event-ID must be an integer."
        ) from None
    if cursor < 0:
        raise PublicApiError(400, "invalid_event_cursor", "Last-Event-ID cannot be negative.")
    repository.require(run_id)

    def generate() -> Iterator[str]:
        current = cursor
        heartbeat_at = time.monotonic() + settings.research_sse_heartbeat_seconds
        yield "retry: 3000\n\n"
        while True:
            events = repository.events_after(run_id, current)
            for event in events:
                current = event.id
                data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"
            if repository.response(run_id).status.terminal and not events:
                return
            now = time.monotonic()
            if now >= heartbeat_at:
                yield ": heartbeat\n\n"
                heartbeat_at = now + settings.research_sse_heartbeat_seconds
            time.sleep(settings.research_sse_poll_seconds)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
