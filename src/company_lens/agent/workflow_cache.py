from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _hydrate_cached_results(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("hydrate_cached_results")
    plan = state.get("execution_plan")
    memory = state.get("session_memory")
    if plan is None or memory is None:
        return _skipped("hydrate_cached_results")
    cache = {(item.kind, item.request_fingerprint): item for item in memory.cached_source_results}
    retrieval_results: list[RetrievalBranchResult] = []
    financial_results: list[FinancialBranchResult] = []
    macro_results: list[MacroBranchResult] = []
    outcomes: list[BranchOutcome] = []
    for branch in _source_branches(plan):
        cached = cache.get((branch.kind, _source_request_fingerprint(branch)))
        if cached is None:
            continue
        if isinstance(branch, DocumentRetrievalBranch) and cached.retrieval_result is not None:
            retrieval_results.append(
                RetrievalBranchResult(branch_id=branch.branch_id, result=cached.retrieval_result)
            )
        elif isinstance(branch, FinancialFactsBranch) and cached.financial_result is not None:
            financial_results.append(
                FinancialBranchResult(branch_id=branch.branch_id, result=cached.financial_result)
            )
        elif isinstance(branch, MacroSeriesBranch) and cached.macro_result is not None:
            if _macro_cache_is_stale_for_latest_query(cached.macro_result):
                continue
            macro_results.append(
                MacroBranchResult(branch_id=branch.branch_id, result=cached.macro_result)
            )
        else:
            continue
        outcomes.append(
            BranchOutcome(
                branch_id=branch.branch_id,
                kind=branch.kind,
                status=BranchStatus.COMPLETED,
                optional=branch.optional,
                attempts=0,
            )
        )
    source_count = len(_source_branches(plan))
    record_cache_access(
        cache="research_session",
        hits=len(outcomes),
        misses=max(0, source_count - len(outcomes)),
    )
    return {
        "retrieval_results": tuple(retrieval_results),
        "financial_results": tuple(financial_results),
        "macro_results": tuple(macro_results),
        "branch_outcomes": tuple(outcomes),
        "trajectory": (
            _event(
                "hydrate_cached_results",
                TrajectoryStatus.COMPLETED,
                "Exact-match session results were hydrated.",
                started,
                details={"reused_results": len(outcomes)},
            ),
        ),
    }


def _macro_cache_is_stale_for_latest_query(result: FredSeriesResult) -> bool:
    query = result.query
    if query.observation_start is not None or query.observation_end is not None:
        return False
    if not result.series or not result.observations:
        return False
    latest_observed_by_series: dict[str, date] = {}
    for observation in result.observations:
        latest_observed = latest_observed_by_series.get(observation.series_id)
        if latest_observed is None or observation.observed_at > latest_observed:
            latest_observed_by_series[observation.series_id] = observation.observed_at
    for series in result.series:
        latest_observed = latest_observed_by_series.get(series.series_id)
        if latest_observed is not None and latest_observed < series.observation_end:
            return True
    return False


def _dispatch_source_branches(state: AgentState) -> list[Send] | str:
    if state["status"] is not AgentRunStatus.RUNNING:
        return "evaluate_context"
    plan = state.get("execution_plan")
    if plan is None:
        return "evaluate_context"
    sends: list[Send] = []
    completed = {
        outcome.branch_id
        for outcome in state.get("branch_outcomes", ())
        if outcome.status is BranchStatus.COMPLETED
    }
    for branch in plan.branches:
        if branch.kind in SOURCE_KINDS and branch.branch_id not in completed:
            sends.append(Send(branch.kind, {**state, "active_branch": branch}))
    return sends or "evaluate_context"

__all__ = ('_hydrate_cached_results', '_macro_cache_is_stale_for_latest_query', '_dispatch_source_branches')  # noqa: E501
