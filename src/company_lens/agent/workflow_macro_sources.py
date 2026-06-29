from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _query_macro_series(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    branch = cast(MacroSeriesBranch, state["active_branch"])
    result, common = _run_source_tool(
        state,
        branch,
        runtime.context.tools.query_macro_series,
        "query_macro_series",
    )
    if result is not None:
        common["macro_results"] = (MacroBranchResult(branch_id=branch.branch_id, result=result),)
    return common


def _run_source_tool[RequestT, ResultT](
    state: AgentState,
    branch: DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch,
    operation: Callable[[RequestT], ResultT],
    node: str,
) -> tuple[ResultT | None, dict[str, object]]:
    started = time.monotonic()
    max_attempts = _source_branch_max_attempts(state, branch.branch_id)
    result: ResultT | None = None
    error: AgentError | None = None
    attempts = 0
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            with observe_operation(
                f"agent.tool.{node}",
                kind="tool",
                attributes={
                    "company_lens.tool.name": node,
                    "company_lens.branch.id": branch.branch_id,
                    "company_lens.retry.attempt": attempt,
                },
            ):
                result = operation(cast(RequestT, branch.request))
            error = None
            break
        except ResearchToolError as exc:
            error = exc.error.model_copy(update={"node": node, "attempt": attempt})
            if not error.recoverable:
                break
        except Exception:
            error = _agent_error(
                node,
                "tool_execution_failed",
                "A research data operation failed.",
                attempt=attempt,
                severity=AgentErrorSeverity.TERMINAL,
            )
            break
    status = BranchStatus.COMPLETED if result is not None else BranchStatus.FAILED
    outcome = BranchOutcome(
        branch_id=branch.branch_id,
        kind=branch.kind,
        status=status,
        optional=branch.optional,
        attempts=attempts,
        error=error,
    )
    update: dict[str, object] = {
        "branch_outcomes": (outcome,),
        "node_attempts": (NodeAttempt(node=f"{node}:{branch.branch_id}", attempts=attempts),),
        "tool_calls_used": attempts,
        "trajectory": (
            _event(
                node,
                TrajectoryStatus.COMPLETED if result is not None else TrajectoryStatus.FAILED,
                "Branch execution completed." if result is not None else "Branch execution failed.",
                started,
                details={"branch_id": branch.branch_id, "attempts": attempts},
            ),
        ),
    }
    if error is not None:
        update["errors"] = (error,)
    return result, update


__all__ = ("_query_macro_series", "_run_source_tool")
