from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from company_lens.config import Settings, get_settings
from company_lens.research.repository import ResearchRunRepository


@dataclass(frozen=True)
class Principal:
    subject: str
    authenticated: bool = False


def get_principal(request: Request) -> Principal:
    actor = request.headers.get("X-Client-ID")
    if actor and 0 < len(actor) <= 128:
        return Principal(subject=f"anonymous:{actor}")
    host = request.client.host if request.client is not None else "unknown"
    return Principal(subject=f"anonymous-ip:{host}")


def get_research_repository(request: Request) -> ResearchRunRepository:
    repository = getattr(request.app.state, "research_repository", None)
    if not isinstance(repository, ResearchRunRepository):
        raise RuntimeError("Research repository is not configured.")
    return repository


def get_api_settings() -> Settings:
    return get_settings()
