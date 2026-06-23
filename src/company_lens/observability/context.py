from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class ObservabilityContext:
    correlation_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None


_CONTEXT: ContextVar[ObservabilityContext] = ContextVar("company_lens_observability_context")


def current_context() -> ObservabilityContext:
    try:
        return _CONTEXT.get()
    except LookupError:
        return ObservabilityContext()


@contextmanager
def bind_context(
    *,
    correlation_id: str | None = None,
    run_id: str | uuid.UUID | None = None,
    session_id: str | None = None,
) -> Iterator[ObservabilityContext]:
    current = current_context()
    updated = ObservabilityContext(
        correlation_id=correlation_id if correlation_id is not None else current.correlation_id,
        run_id=str(run_id) if run_id is not None else current.run_id,
        session_id=session_id if session_id is not None else current.session_id,
    )
    token: Token[ObservabilityContext] = _CONTEXT.set(updated)
    try:
        yield updated
    finally:
        _CONTEXT.reset(token)
