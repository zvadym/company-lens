from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _normalize_and_validate_plan(
    plan: ExecutionPlan,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    policy: ExecutionPolicy,
    *,
    retrieval_index_name: str,
    retrieval_index_version: str,
) -> ExecutionPlan:
    if plan.route is not analysis.route:
        raise ValueError("Plan route must match question analysis.")
    normalized: list[ExecutionBranch] = []
    for branch in plan.branches:
        if isinstance(branch, DocumentRetrievalBranch):
            retrieval_request = branch.request.model_copy(
                update={
                    "index_name": retrieval_index_name,
                    "index_version": retrieval_index_version,
                    "evidence_scope": "documents",
                }
            )
            branch = branch.model_copy(update={"request": retrieval_request})
        if (
            isinstance(branch, FinancialFactsBranch)
            and not branch.request.company_ids
            and not branch.request.tickers
            and len(resolved.company_ids) == 1
        ):
            financial_request = branch.request.model_copy(
                update={"company_ids": resolved.company_ids}
            )
            branch = branch.model_copy(update={"request": financial_request})
        if isinstance(branch, CalculationBranch) and set(branch.depends_on) != set(
            branch.input_refs
        ):
            branch = branch.model_copy(update={"depends_on": branch.input_refs})
        normalized.append(branch)
    plan = plan.model_copy(update={"branches": tuple(normalized)})
    plan = _normalize_default_chart_window(plan, analysis, resolved)
    if len([item for item in plan.branches if isinstance(item, ChartBranch)]) > 1:
        raise ValueError("Only one chart branch is supported.")
    source = _source_branches(plan)
    if len(source) > policy.max_tool_calls:
        raise ValueError("Execution plan exceeds the tool-call budget.")
    known_company_ids = set(resolved.company_ids)
    for branch in plan.branches:
        if (
            isinstance(branch, FinancialFactsBranch)
            and set(branch.request.company_ids) - known_company_ids
        ):
            raise ValueError("Financial plan contains an unresolved company ID.")
        if branch.kind in SOURCE_KINDS and branch.depends_on:
            raise ValueError("Source branches must be independent.")
    by_id = {item.branch_id: item for item in plan.branches}
    normalized_chart = _normalize_chart_branch(plan)
    if normalized_chart is not None:
        plan = plan.model_copy(
            update={
                "branches": tuple(
                    normalized_chart if branch.branch_id == normalized_chart.branch_id else branch
                    for branch in plan.branches
                )
            }
        )
        by_id = {item.branch_id: item for item in plan.branches}
    for branch in plan.branches:
        if isinstance(branch, CalculationBranch):
            if set(branch.depends_on) != set(branch.input_refs):
                raise ValueError("Calculation dependencies must equal input references.")
            for reference in branch.input_refs:
                source_branch = by_id[reference]
                if not isinstance(source_branch, (FinancialFactsBranch, MacroSeriesBranch)):
                    raise ValueError("Calculations require numeric source branches.")
                _validate_single_series_request(source_branch)
        if isinstance(branch, ChartBranch):
            chart_refs = _chart_references(branch)
            for reference in chart_refs:
                if not isinstance(
                    by_id[reference],
                    (FinancialFactsBranch, MacroSeriesBranch, CalculationBranch),
                ):
                    raise ValueError("Chart requires numeric dataset references.")
    _validate_route_shape(plan)
    represented = _represented_capabilities(plan)
    if not set(analysis.required_capabilities).issubset(represented):
        raise ValueError("Execution plan does not implement all required capabilities.")
    return plan


__all__ = ("_normalize_and_validate_plan",)
