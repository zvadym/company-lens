from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _terminal_model_status(error: AgentError) -> AgentRunStatus:
    return (
        AgentRunStatus.ABSTAINED
        if error.category is AgentErrorCategory.PROVIDER_REFUSAL
        else AgentRunStatus.FAILED
    )


def _terminal_parse_status(error: AgentError) -> AgentRunStatus:
    if error.category is AgentErrorCategory.PROVIDER_AUTH:
        return AgentRunStatus.FAILED
    return AgentRunStatus.ABSTAINED


def _parse_failure_answer(state: AgentState, error: AgentError) -> str:
    question = _latest_user_question(state)
    details = [
        "I could not start the research because the system could not classify the request.",
        "No company reports, financial facts, macro series, or chart data were queried.",
    ]
    if _looks_like_incomplete_comparison(question):
        peer = _comparison_target(question) or "the peer company"
        details.append(
            f"The comparison target also looks incomplete: specify which {peer} metric should "
            "be used in the chart."
        )
    suggestions = "\n".join(f"- {item}" for item in _suggested_query_rewrites(question))
    return (
        "## I could not start this research\n\n"
        + "\n\n".join(details)
        + "\n\nTry one of these instead:\n\n"
        + suggestions
    )


def _latest_user_question(state: AgentState) -> str:
    for message in reversed(state.get("messages", ())):
        if message.role == "user":
            return message.content
    return "the research question"


def _looks_like_incomplete_comparison(question: str) -> bool:
    target = _comparison_target(question)
    if target is None:
        return False
    metric_terms = {
        "asset",
        "cash",
        "debt",
        "fedfunds",
        "free cash flow",
        "growth",
        "income",
        "liabilit",
        "margin",
        "profit",
        "rate",
        "revenue",
        "sales",
        "stock",
        "subscriber",
    }
    normalized_target = target.lower()
    return not any(term in normalized_target for term in metric_terms)


def _suggested_query_rewrites(question: str) -> tuple[str, ...]:
    normalized = " ".join(question.split())
    comparison = _comparison_parts(normalized)
    if comparison is not None:
        left, target = comparison
        return (
            f"{left} against {target} revenue growth.",
            f"{left} against {target} revenue.",
            f"{left} against {target} operating margin.",
        )
    if "plot" in normalized.lower() or "chart" in normalized.lower():
        return (
            "Plot Cloudflare revenue growth over the last eight quarters.",
            "Plot Cloudflare revenue growth against the federal funds rate.",
            "Plot one company metric against one specific peer or macro metric.",
        )
    return (
        "Compare Cloudflare revenue growth over the last eight quarters.",
        "Summarize Netflix revenue growth from the latest available filings.",
        "Ask for one company, one metric, and an optional date range.",
    )


def _comparison_parts(question: str) -> tuple[str, str] | None:
    normalized = " ".join(question.split()).strip(" .")
    marker = " against "
    index = normalized.lower().find(marker)
    if index < 0:
        return None
    left = normalized[:index].strip()
    target = normalized[index + len(marker) :].strip(" .")
    if target.lower().startswith("the "):
        target = target[4:].strip()
    if not left or not target:
        return None
    return left, target


def _comparison_target(question: str) -> str | None:
    parts = _comparison_parts(question)
    return parts[1] if parts is not None else None


def _provider_refusal(node: str, attempt: int) -> AgentError:
    return AgentError(
        category=AgentErrorCategory.PROVIDER_REFUSAL,
        severity=AgentErrorSeverity.TERMINAL,
        code="model_refusal",
        message="The model declined the requested operation.",
        node=node,
        attempt=attempt,
    )


def _validation_error(node: str, code: str) -> AgentError:
    return AgentError(
        category=AgentErrorCategory.VALIDATION,
        severity=AgentErrorSeverity.TERMINAL,
        code=code,
        message="The research workflow received an invalid typed state or plan.",
        node=node,
    )


def _agent_error(
    node: str,
    code: str,
    message: str,
    *,
    category: AgentErrorCategory = AgentErrorCategory.TOOL,
    severity: AgentErrorSeverity = AgentErrorSeverity.RECOVERABLE,
    attempt: int = 1,
) -> AgentError:
    return AgentError(
        category=category,
        severity=severity,
        code=code,
        message=message,
        node=node,
        attempt=attempt,
    )


def _event(
    node: str,
    status: TrajectoryStatus,
    summary: str,
    started: float,
    *,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> TrajectoryEvent:
    return TrajectoryEvent(
        node=node,
        status=status,
        occurred_at=datetime.now(UTC),
        summary=summary,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        details=details or {},
    )


def _failed_event(node: str, started: float) -> TrajectoryEvent:
    return _event(node, TrajectoryStatus.FAILED, "Workflow node failed.", started)


def _skipped(node: str) -> dict[str, object]:
    return {
        "trajectory": (
            TrajectoryEvent(
                node=node,
                status=TrajectoryStatus.SKIPPED,
                occurred_at=datetime.now(UTC),
                summary="Workflow node was skipped.",
            ),
        )
    }

__all__ = ('_terminal_model_status', '_terminal_parse_status', '_parse_failure_answer', '_latest_user_question', '_looks_like_incomplete_comparison', '_suggested_query_rewrites', '_comparison_parts', '_comparison_target', '_provider_refusal', '_validation_error', '_agent_error', '_event', '_failed_event', '_skipped')  # noqa: E501
