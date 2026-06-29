from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _fallback_follow_up_analysis(
    question: str,
    memory: SessionMemory | None,
) -> QuestionAnalysis | None:
    if memory is None or (memory.last_execution_plan is None and not memory.recent_artifacts):
        return None
    if not (
        _question_references_previous_work(question)
        or _question_requests_add_series(question)
        or _period_override(question) is not None
    ):
        return None
    represented = (
        _represented_capabilities(memory.last_execution_plan)
        if memory.last_execution_plan is not None
        else {
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        }
    )
    if not represented:
        return None
    chart_requested = AgentCapability.CHART in represented or _question_requests_chart(question)
    capabilities = set(represented)
    if chart_requested:
        capabilities.add(AgentCapability.CHART)
    ordered_capabilities = tuple(
        capability for capability in AgentCapability if capability in capabilities
    )
    if not ordered_capabilities:
        return None
    route = _fallback_follow_up_route(capabilities, memory.last_execution_plan)
    reason_codes = ["heuristic_follow_up_parse", "deterministic_replay_candidate"]
    if _requested_chart_type(question) is not None:
        reason_codes.append("chart_type_override")
    if _period_override(question) is not None:
        reason_codes.append("period_override")
    if _question_requests_add_series(question):
        reason_codes.append("adds_company")
    if _question_references_previous_work(question):
        reason_codes.append("same_data")
    return QuestionAnalysis(
        normalized_question=question,
        route=route,
        required_capabilities=ordered_capabilities,
        chart_requested=chart_requested,
        is_follow_up=True,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _fallback_follow_up_route(
    capabilities: set[AgentCapability],
    previous_plan: ExecutionPlan | None,
) -> ResearchRoute:
    if AgentCapability.CALCULATIONS in capabilities:
        return ResearchRoute.CALCULATION
    if {
        AgentCapability.DOCUMENTS,
        AgentCapability.FINANCIAL_FACTS,
    }.issubset(capabilities) or {
        AgentCapability.MACRO_SERIES,
        AgentCapability.FINANCIAL_FACTS,
    }.issubset(capabilities):
        return ResearchRoute.HYBRID
    if AgentCapability.FINANCIAL_FACTS in capabilities:
        return ResearchRoute.STRUCTURED_ONLY
    if AgentCapability.MACRO_SERIES in capabilities:
        return ResearchRoute.API_ONLY
    if AgentCapability.DOCUMENTS in capabilities:
        return ResearchRoute.RAG_ONLY
    return previous_plan.route if previous_plan is not None else ResearchRoute.UNSUPPORTED


def _answer_session_context(state: AgentState) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("answer_session_context")
    started = time.monotonic()
    analysis = state.get("analysis")
    memory = state.get("session_memory")
    answer = _previous_chart_context_answer(state["question"], analysis, memory)
    if answer is None:
        return _skipped("answer_session_context")
    return {
        "status": AgentRunStatus.COMPLETED,
        "final_answer": answer,
        "messages": (
            SessionMessage(role="assistant", content=answer, created_at=datetime.now(UTC)),
        ),
        "trajectory": (
            _event(
                "answer_session_context",
                TrajectoryStatus.COMPLETED,
                "Answered from the previous chart in session memory.",
                started,
            ),
        ),
    }


def _route_after_session_context(state: AgentState) -> Literal["resolve_entities", "__end__"]:
    return "__end__" if state["status"] is AgentRunStatus.COMPLETED else "resolve_entities"


def _previous_chart_context_answer(
    question: str,
    analysis: QuestionAnalysis | None,
    memory: SessionMemory | None,
) -> str | None:
    if memory is None:
        return None
    if not _asks_about_previous_chart_context(question, analysis):
        return None
    artifact = _selected_chart_artifact(memory)
    if artifact is None:
        return _legacy_previous_chart_context_answer(question, memory.last_chart_spec)
    if artifact.period_start is None or artifact.period_end is None or artifact.point_count is None:
        return None
    series_labels = ", ".join(artifact.series_labels)
    if _looks_ukrainian(question):
        return (
            "## Період графіка\n\n"
            "Останній релевантний графік "
            f"`{artifact.artifact_id}` був за період з "
            f"{artifact.period_start.isoformat()} до {artifact.period_end.isoformat()}.\n\n"
            "## Кількість звітних періодів\n\n"
            f"На графіку було {artifact.point_count} точок, тобто {artifact.point_count} останніх "
            "звітних періодів у побудованому наборі даних.\n\n"
            "## Серії\n\n"
            f"Серії на графіку: {series_labels}."
        )
    return (
        "## Chart Period\n\n"
        f"The latest relevant chart `{artifact.artifact_id}` covered "
        f"{artifact.period_start.isoformat()} through {artifact.period_end.isoformat()}.\n\n"
        "## Report Count\n\n"
        f"The chart had {artifact.point_count} points, meaning {artifact.point_count} "
        "latest reporting periods in the plotted dataset.\n\n"
        "## Series\n\n"
        f"The chart series were: {series_labels}."
    )


def _selected_chart_artifact(memory: SessionMemory) -> SessionArtifactContext | None:
    return next(
        (artifact for artifact in reversed(memory.recent_artifacts) if artifact.kind == "chart"),
        None,
    )


def _legacy_previous_chart_context_answer(
    question: str,
    chart: ChartSpecification | None,
) -> str | None:
    if chart is None or not chart.data:
        return None
    dates = tuple(point.x for point in chart.data)
    artifact = SessionArtifactContext(
        artifact_id="chart:latest",
        run_id=uuid.UUID(int=0),
        user_question="",
        title=chart.title,
        chart_type=chart.chart_type,
        series_labels=tuple(series.label for series in chart.series),
        period_start=min(dates),
        period_end=max(dates),
        point_count=len(chart.data),
    )
    return _previous_chart_context_answer(
        question,
        QuestionAnalysis(
            normalized_question=question,
            route=ResearchRoute.UNSUPPORTED,
            reason_codes=("previous_chart",),
        ),
        SessionMemory(recent_artifacts=(artifact,)),
    )


def _asks_about_previous_chart_context(
    question: str,
    analysis: QuestionAnalysis | None,
) -> bool:
    normalized = question.casefold()
    if _question_requests_chart_rebuild(normalized):
        return False
    reason_codes = analysis.reason_codes if analysis is not None else ()
    if any(
        marker in reason
        for reason in reason_codes
        for marker in (
            "previous_output",
            "previous_chart",
            "covered_period",
            "number_of_reports",
        )
    ):
        return True
    return ("графік" in normalized or "chart" in normalized or "plot" in normalized) and (
        "період" in normalized
        or "period" in normalized
        or "репорт" in normalized
        or "report" in normalized
        or "скільки" in normalized
        or "how many" in normalized
    )


def _question_requests_chart_rebuild(normalized_question: str) -> bool:
    return any(
        marker in normalized_question
        for marker in (
            "побудуй",
            "побудувати",
            "намалюй",
            "покажи",
            "build",
            "plot",
            "chart ",
            "show ",
        )
    )


__all__ = (
    "_fallback_follow_up_analysis",
    "_fallback_follow_up_route",
    "_answer_session_context",
    "_route_after_session_context",
    "_previous_chart_context_answer",
    "_selected_chart_artifact",
    "_legacy_previous_chart_context_answer",
    "_asks_about_previous_chart_context",
    "_question_requests_chart_rebuild",
)  # noqa: E501
