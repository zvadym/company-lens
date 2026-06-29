from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _branch_has_evidence(
    state: AgentState,
    branch: DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch,
) -> bool:
    if isinstance(branch, DocumentRetrievalBranch):
        retrieval_result = next(
            (
                value
                for value in state.get("retrieval_results", ())
                if value.branch_id == branch.branch_id
            ),
            None,
        )
        return bool(
            retrieval_result
            and retrieval_result.result.context
            and not retrieval_result.result.trace.abstained
        )
    if isinstance(branch, FinancialFactsBranch):
        financial_result = next(
            (
                value
                for value in state.get("financial_results", ())
                if value.branch_id == branch.branch_id
            ),
            None,
        )
        return bool(financial_result and financial_result.result.observations)
    macro_result = next(
        (value for value in state.get("macro_results", ()) if value.branch_id == branch.branch_id),
        None,
    )
    return bool(macro_result and macro_result.result.observations)


def _has_any_source_evidence(state: AgentState) -> bool:
    return bool(
        any(item.result.context for item in state.get("retrieval_results", ()))
        or any(item.result.observations for item in state.get("financial_results", ()))
        or any(item.result.observations for item in state.get("macro_results", ()))
    )


def _failed_planned_branches[BranchT: ExecutionBranch](
    state: AgentState, branch_type: type[BranchT]
) -> tuple[BranchT, ...]:
    plan = state["execution_plan"]
    if plan is None:
        return ()
    outcomes = {item.branch_id: item for item in state.get("branch_outcomes", ())}
    return tuple(
        branch
        for branch in plan.branches
        if isinstance(branch, branch_type)
        and (
            branch.branch_id not in outcomes
            or outcomes[branch.branch_id].status is BranchStatus.FAILED
        )
    )


__all__ = ("_branch_has_evidence", "_has_any_source_evidence", "_failed_planned_branches")
