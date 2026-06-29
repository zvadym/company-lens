from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _route_after_repair(
    state: AgentState,
) -> Literal["validate_citations", "finalize_response"]:
    return (
        "finalize_response"
        if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}
        else "validate_citations"
    )


def _finalize_response(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    status = state["status"]
    validation = state.get("answer_validation")
    draft_answer = state.get("draft_answer")
    answer = _normalize_answer_number_formatting(draft_answer) if draft_answer else None
    promote_current_context = (
        status in {AgentRunStatus.RUNNING, AgentRunStatus.PARTIAL}
        and answer is not None
        and validation is not None
        and validation.valid
    )
    memory = _updated_session_memory(
        state,
        runtime.context.max_cached_source_results,
        promote_current_context=promote_current_context,
    )
    if status in {AgentRunStatus.RUNNING, AgentRunStatus.PARTIAL}:
        if answer and validation is not None and validation.valid:
            final_status = (
                AgentRunStatus.PARTIAL
                if status is AgentRunStatus.PARTIAL
                else AgentRunStatus.COMPLETED
            )
            return {
                "status": final_status,
                "final_answer": answer,
                "messages": (
                    SessionMessage(role="assistant", content=answer, created_at=datetime.now(UTC)),
                ),
                "session_memory": memory,
                "trajectory": (
                    _event(
                        "finalize_response",
                        TrajectoryStatus.COMPLETED,
                        "Research response finalized.",
                        started,
                    ),
                ),
            }
        status = AgentRunStatus.ABSTAINED
    if status is AgentRunStatus.ABSTAINED and answer:
        return {
            "status": status,
            "final_answer": answer,
            "messages": (
                SessionMessage(role="assistant", content=answer, created_at=datetime.now(UTC)),
            ),
            "session_memory": memory,
            "trajectory": (
                _event(
                    "finalize_response",
                    TrajectoryStatus.COMPLETED,
                    "Research run finalized with a user-facing explanation.",
                    started,
                ),
            ),
        }
    return {
        "status": status,
        "final_answer": None,
        "session_memory": memory,
        "trajectory": (
            _event(
                "finalize_response",
                TrajectoryStatus.COMPLETED,
                "Research run finalized without a generated answer.",
                started,
            ),
        ),
    }


def _updated_session_memory(
    state: AgentState,
    cache_limit: int,
    *,
    promote_current_context: bool,
) -> SessionMemory:
    previous = state.get("session_memory") or SessionMemory()
    stored_at = datetime.now(UTC)
    if not promote_current_context:
        return previous.model_copy(update={"updated_at": stored_at})
    cached = {
        (item.kind, item.request_fingerprint): item for item in previous.cached_source_results
    }
    plan = state.get("execution_plan")
    branches = {branch.branch_id: branch for branch in plan.branches} if plan else {}
    for retrieval in state.get("retrieval_results", ()):
        branch = branches.get(retrieval.branch_id)
        if isinstance(branch, DocumentRetrievalBranch) and retrieval.result.context:
            entry = CachedSourceResult(
                kind=branch.kind,
                request_fingerprint=_source_request_fingerprint(branch),
                stored_at=stored_at,
                retrieval_result=retrieval.result,
            )
            cached[(entry.kind, entry.request_fingerprint)] = entry
    for financial in state.get("financial_results", ()):
        branch = branches.get(financial.branch_id)
        if isinstance(branch, FinancialFactsBranch) and financial.result.observations:
            entry = CachedSourceResult(
                kind=branch.kind,
                request_fingerprint=_source_request_fingerprint(branch),
                stored_at=stored_at,
                financial_result=financial.result,
            )
            cached[(entry.kind, entry.request_fingerprint)] = entry
    for macro in state.get("macro_results", ()):
        branch = branches.get(macro.branch_id)
        if isinstance(branch, MacroSeriesBranch) and macro.result.observations:
            entry = CachedSourceResult(
                kind=branch.kind,
                request_fingerprint=_source_request_fingerprint(branch),
                stored_at=stored_at,
                macro_result=macro.result,
            )
            cached[(entry.kind, entry.request_fingerprint)] = entry
    resolved = state.get("resolved_query")
    entries = tuple(sorted(cached.values(), key=lambda item: item.stored_at)[-cache_limit:])
    chart = state.get("chart_spec")
    artifacts = _updated_recent_artifacts(
        previous.recent_artifacts,
        _chart_artifact_context(state, chart) if chart is not None else None,
    )
    return SessionMemory(
        last_resolved_query=resolved or previous.last_resolved_query,
        recent_resolved_queries=_updated_recent_resolved_queries(
            previous.recent_resolved_queries,
            resolved,
        ),
        last_execution_plan=plan or previous.last_execution_plan,
        last_chart_spec=chart or previous.last_chart_spec,
        recent_artifacts=artifacts,
        cached_source_results=entries,
        evidence=state.get("evidence", ()) or previous.evidence,
        updated_at=stored_at,
    )


def _chart_artifact_context(
    state: AgentState,
    chart: ChartSpecification,
) -> SessionArtifactContext | None:
    if not chart.data:
        return None
    plan = state.get("execution_plan")
    resolved = state.get("resolved_query")
    dates = tuple(point.x for point in chart.data)
    return SessionArtifactContext(
        artifact_id=f"chart:{state['run_id']}",
        run_id=state["run_id"],
        user_question=state["question"],
        title=chart.title,
        chart_type=chart.chart_type,
        series_labels=tuple(series.label for series in chart.series),
        company_ids=resolved.company_ids if resolved is not None else (),
        metrics=resolved.metrics if resolved is not None else (),
        calculations=tuple(
            branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
        )
        if plan is not None
        else (),
        period_start=min(dates),
        period_end=max(dates),
        point_count=len(chart.data),
        source_branch_ids=tuple(branch.branch_id for branch in _source_branches(plan))
        if plan is not None
        else (),
    )


def _updated_recent_artifacts(
    previous: tuple[SessionArtifactContext, ...],
    current: SessionArtifactContext | None,
    *,
    limit: int = 8,
) -> tuple[SessionArtifactContext, ...]:
    if current is None:
        return previous[-limit:]
    retained = tuple(item for item in previous if item.artifact_id != current.artifact_id)
    return (*retained, current)[-limit:]


def _planning_artifact_context(memory: SessionMemory | None) -> tuple[dict[str, object], ...]:
    if memory is None:
        return ()
    return tuple(
        {
            "artifact_id": artifact.artifact_id,
            "run_id": str(artifact.run_id),
            "kind": artifact.kind,
            "user_question": artifact.user_question,
            "title": artifact.title,
            "chart_type": artifact.chart_type,
            "series_labels": artifact.series_labels,
            "company_ids": tuple(str(company_id) for company_id in artifact.company_ids),
            "metrics": artifact.metrics,
            "calculations": artifact.calculations,
            "period": {
                "start": artifact.period_start.isoformat()
                if artifact.period_start is not None
                else None,
                "end": artifact.period_end.isoformat() if artifact.period_end is not None else None,
                "point_count": artifact.point_count,
            },
            "source_branch_ids": artifact.source_branch_ids,
        }
        for artifact in memory.recent_artifacts
    )


__all__ = (
    "_route_after_repair",
    "_finalize_response",
    "_updated_session_memory",
    "_chart_artifact_context",
    "_updated_recent_artifacts",
    "_planning_artifact_context",
)  # noqa: E501
