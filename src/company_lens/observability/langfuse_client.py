from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from company_lens.config import Settings

_client: Any | None = None


class LangfuseClientUnavailable(RuntimeError):
    pass


class LangfuseProjectMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class LangfuseProjectInfo:
    id: str
    name: str | None


def configure_langfuse_client(
    settings: Settings,
    *,
    should_export_span: Any | None = None,
) -> Any | None:
    global _client
    if _client is not None:
        return _client
    secret_key = (
        settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else None
    )
    if not settings.langfuse_public_key or not secret_key:
        return None
    from langfuse import Langfuse

    kwargs: dict[str, Any] = {
        "public_key": settings.langfuse_public_key,
        "secret_key": secret_key,
        "base_url": settings.langfuse_base_url,
        "environment": settings.environment,
        "release": settings.service_version,
    }
    if should_export_span is not None:
        kwargs["should_export_span"] = should_export_span
    _client = Langfuse(**kwargs)
    return _client


def current_langfuse_client() -> Any:
    if _client is None:
        raise LangfuseClientUnavailable("Langfuse client is not configured.")
    return _client


def set_langfuse_client(client: Any) -> None:
    global _client
    _client = client


def reset_langfuse_client() -> None:
    global _client
    _client = None


def shutdown_langfuse_client() -> None:
    global _client
    if _client is None:
        return
    try:
        shutdown = getattr(_client, "shutdown", None)
        if shutdown is not None:
            shutdown()
        else:
            _client.flush()
    finally:
        _client = None


def verify_langfuse_project(client: Any, expected_project_id: str | None) -> LangfuseProjectInfo:
    if not expected_project_id:
        raise LangfuseClientUnavailable("Expected Langfuse project ID is not configured.")
    project = resolve_langfuse_project(client)
    if project.id != expected_project_id:
        raise LangfuseProjectMismatch("Langfuse project does not match the expected project.")
    return project


def resolve_langfuse_project(client: Any) -> LangfuseProjectInfo:
    try:
        response = client.api.projects.get()
        projects = _value(response, "data")
        if projects is not None:
            if not isinstance(projects, (list, tuple)) or len(projects) != 1:
                raise LangfuseClientUnavailable(
                    "Langfuse project-scoped identity returned an ambiguous project set."
                )
            project = projects[0]
        else:
            project = response
        project_id = _value(project, "id")
        project_name = _value(project, "name")
    except Exception as exc:
        raise LangfuseClientUnavailable("Langfuse project identity is unavailable.") from exc
    if not isinstance(project_id, str) or not project_id:
        raise LangfuseClientUnavailable("Langfuse project identity is unavailable.")
    return LangfuseProjectInfo(
        id=project_id,
        name=project_name if isinstance(project_name, str) else None,
    )


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
