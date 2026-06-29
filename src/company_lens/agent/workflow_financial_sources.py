from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _retrieve_documents(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    branch = cast(DocumentRetrievalBranch, state["active_branch"])
    result, common = _run_source_tool(
        state,
        branch,
        runtime.context.tools.retrieve_documents,
        "retrieve_documents",
    )
    if result is not None:
        record_retrieval(
            strategy=str(result.plan.strategy),
            result_count=sum(attempt.evidence_count for attempt in result.trace.attempts),
            context_count=len(result.context),
        )
        common["retrieval_results"] = (
            RetrievalBranchResult(branch_id=branch.branch_id, result=result),
        )
    return common


def _query_financial_facts(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    branch = cast(FinancialFactsBranch, state["active_branch"])
    result, common = _run_source_tool(
        state,
        branch,
        runtime.context.tools.query_financial_facts,
        "query_financial_facts",
    )
    if result is not None:
        result = _query_annual_financial_fallback_if_needed(
            state,
            branch,
            result,
            common,
            runtime.context.tools,
        )
        common["financial_results"] = (
            FinancialBranchResult(branch_id=branch.branch_id, result=result),
        )
    return common


def _query_annual_financial_fallback_if_needed(
    state: AgentState,
    branch: FinancialFactsBranch,
    result: FinancialFactQueryResult,
    update: dict[str, object],
    tools: ResearchTools,
) -> FinancialFactQueryResult:
    fallback_request = _annual_financial_fallback_request(state, branch, result)
    if fallback_request is None:
        return result
    _record_financial_fallback_attempt(update, branch.branch_id)
    started = time.monotonic()
    try:
        fallback = tools.query_financial_facts(fallback_request)
    except ResearchToolError as exc:
        error = exc.error.model_copy(update={"node": "query_financial_facts", "attempt": 1})
        _append_update_tuple(update, "errors", (error,))
        _append_update_tuple(
            update,
            "trajectory",
            (
                _event(
                    "query_financial_facts",
                    TrajectoryStatus.FAILED,
                    "Annual financial fallback query failed.",
                    started,
                    details={"branch_id": branch.branch_id},
                ),
            ),
        )
        return _financial_result_with_warnings(result, "annual_financial_fallback_failed")
    except Exception:
        error = _agent_error(
            "query_financial_facts",
            "annual_financial_fallback_failed",
            "Annual financial fallback query failed.",
            category=AgentErrorCategory.TOOL,
            severity=AgentErrorSeverity.RECOVERABLE,
        )
        _append_update_tuple(update, "errors", (error,))
        _append_update_tuple(
            update,
            "trajectory",
            (
                _event(
                    "query_financial_facts",
                    TrajectoryStatus.FAILED,
                    "Annual financial fallback query failed.",
                    started,
                    details={"branch_id": branch.branch_id},
                ),
            ),
        )
        return _financial_result_with_warnings(result, "annual_financial_fallback_failed")
    fallback_status = (
        "annual_financial_fallback_used"
        if fallback.observations
        else "annual_financial_fallback_missing"
    )
    _append_update_tuple(
        update,
        "trajectory",
        (
            _event(
                "query_financial_facts",
                TrajectoryStatus.COMPLETED,
                "Annual financial fallback query completed.",
                started,
                details={
                    "branch_id": branch.branch_id,
                    "fallback_observations": len(fallback.observations),
                },
            ),
        ),
    )
    if fallback.observations:
        return _financial_result_with_warnings(
            fallback,
            "quarterly_financial_facts_missing",
            fallback_status,
        )
    return _financial_result_with_warnings(
        result,
        "quarterly_financial_facts_missing",
        fallback_status,
        *fallback.warnings,
    )


def _annual_financial_fallback_request(
    state: AgentState,
    branch: FinancialFactsBranch,
    result: FinancialFactQueryResult,
) -> FinancialFactQuery | None:
    if result.observations:
        return None
    request = branch.request
    if request.period_types != ("quarter",) or request.fiscal_periods:
        return None
    operations = _financial_branch_calculation_operations(
        state.get("execution_plan"),
        branch.branch_id,
    )
    if not operations or any(
        operation not in ANNUAL_FINANCIAL_FALLBACK_OPERATIONS for operation in operations
    ):
        return None
    minimum_limit = max(_minimum_observations_for_operation(operation) for operation in operations)
    # The fallback changes only the reporting cadence. Company, metric, date, unit, and
    # amendment filters stay intact so the replayed plan cannot drift to another question.
    return request.model_copy(
        update={
            "period_types": ("annual",),
            "fiscal_periods": (),
            "limit": max(request.limit, minimum_limit),
        }
    )


def _financial_branch_calculation_operations(
    plan: ExecutionPlan | None,
    branch_id: str,
) -> tuple[CalculationOperation, ...]:
    if plan is None:
        return ()
    return tuple(
        branch.operation
        for branch in plan.branches
        if isinstance(branch, CalculationBranch) and branch_id in branch.input_refs
    )


def _record_financial_fallback_attempt(update: dict[str, object], branch_id: str) -> None:
    update["tool_calls_used"] = cast(int, update.get("tool_calls_used", 0)) + 1
    outcomes = cast(tuple[BranchOutcome, ...], update.get("branch_outcomes", ()))
    update["branch_outcomes"] = tuple(
        outcome.model_copy(update={"attempts": outcome.attempts + 1})
        if outcome.branch_id == branch_id
        else outcome
        for outcome in outcomes
    )
    attempt_node = f"query_financial_facts:{branch_id}"
    attempts = cast(tuple[NodeAttempt, ...], update.get("node_attempts", ()))
    update["node_attempts"] = tuple(
        item.model_copy(update={"attempts": item.attempts + 1})
        if item.node == attempt_node
        else item
        for item in attempts
    )


def _financial_result_with_warnings(
    result: FinancialFactQueryResult,
    *warnings: str,
) -> FinancialFactQueryResult:
    return result.model_copy(
        update={"warnings": tuple(dict.fromkeys((*result.warnings, *warnings)))}
    )


def _append_update_tuple[ItemT](
    update: dict[str, object],
    key: str,
    values: tuple[ItemT, ...],
) -> None:
    update[key] = (*cast(tuple[ItemT, ...], update.get(key, ())), *values)


__all__ = (
    "_retrieve_documents",
    "_query_financial_facts",
    "_query_annual_financial_fallback_if_needed",
    "_annual_financial_fallback_request",
    "_financial_branch_calculation_operations",
    "_record_financial_fallback_attempt",
    "_financial_result_with_warnings",
    "_append_update_tuple",
)  # noqa: E501
