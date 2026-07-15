from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


_SOURCE_CAPABILITY_BY_KIND = {
    "retrieve_documents": AgentCapability.DOCUMENTS,
    "query_financial_facts": AgentCapability.FINANCIAL_FACTS,
    "query_macro_series": AgentCapability.MACRO_SERIES,
}


def _constrain_plan_sources(
    plan: ExecutionPlan,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
) -> ExecutionPlan:
    """Remove model-added source kinds that the classified request did not authorize."""

    if not DETERMINISTIC_PLAN_REASON_CODES.isdisjoint(plan.reason_codes):
        return plan
    represented = {
        _SOURCE_CAPABILITY_BY_KIND[branch.kind]
        for branch in plan.branches
        if branch.kind in SOURCE_KINDS
    }
    allowed = _allowed_source_capabilities(analysis, resolved, represented)
    if not allowed:
        return plan
    # A plan that replaces the parser's source entirely may be correcting classification.
    # Only constrain plans that already satisfy the classified source requirements.
    if not allowed.issubset(represented):
        return plan
    removed = {
        branch.branch_id
        for branch in plan.branches
        if branch.kind in SOURCE_KINDS and _SOURCE_CAPABILITY_BY_KIND[branch.kind] not in allowed
    }
    if not removed:
        return plan

    changed = True
    while changed:
        changed = False
        for branch in plan.branches:
            if branch.branch_id in removed:
                continue
            if _plan_branch_references(branch) & removed:
                removed.add(branch.branch_id)
                changed = True

    return plan.model_copy(
        update={
            "branches": tuple(
                branch for branch in plan.branches if branch.branch_id not in removed
            ),
            "reason_codes": tuple(
                dict.fromkeys((*plan.reason_codes, "unrequested_source_branches_removed"))
            ),
        }
    )


def _ensure_required_growth_calculations(
    plan: ExecutionPlan,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
) -> ExecutionPlan:
    if (
        AgentCapability.CALCULATIONS not in analysis.required_capabilities
        or any(isinstance(branch, CalculationBranch) for branch in plan.branches)
        or not _explicit_growth_requested(analysis, resolved)
    ):
        return plan
    financial_sources = tuple(
        branch for branch in plan.branches if isinstance(branch, FinancialFactsBranch)
    )
    macro_sources = tuple(
        branch for branch in plan.branches if isinstance(branch, MacroSeriesBranch)
    )
    numeric_sources = financial_sources or macro_sources
    if not numeric_sources:
        return plan

    existing_ids = {branch.branch_id for branch in plan.branches}
    calculations: list[CalculationBranch] = []
    operation = _requested_growth_operation(analysis, resolved, None)
    for source in numeric_sources:
        branch_id = _unique_growth_branch_id(source.branch_id, existing_ids)
        existing_ids.add(branch_id)
        calculations.append(
            CalculationBranch(
                branch_id=branch_id,
                operation=operation,
                input_refs=(source.branch_id,),
                depends_on=(source.branch_id,),
            )
        )
    chart_index = next(
        (index for index, branch in enumerate(plan.branches) if isinstance(branch, ChartBranch)),
        len(plan.branches),
    )
    branches = (
        *plan.branches[:chart_index],
        *calculations,
        *plan.branches[chart_index:],
    )
    return plan.model_copy(
        update={
            "branches": branches,
            "reason_codes": tuple(
                dict.fromkeys((*plan.reason_codes, "inferred_growth_calculation_branch"))
            ),
        }
    )


def _unique_growth_branch_id(source_id: str, existing_ids: set[str]) -> str:
    base = f"{source_id}_growth"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _allowed_source_capabilities(
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    represented: set[AgentCapability],
) -> set[AgentCapability]:
    allowed = set(analysis.required_capabilities) & set(_SOURCE_CAPABILITY_BY_KIND.values())
    if "unsupported_analysis_normalized" not in analysis.reason_codes:
        return allowed
    if (
        resolved.company_ids
        and resolved.metrics
        and AgentCapability.FINANCIAL_FACTS in represented
        and not _explicit_document_research(resolved.query)
    ):
        return {AgentCapability.FINANCIAL_FACTS}
    return set()


def _explicit_document_research(question: str) -> bool:
    normalized = question.casefold()
    return any(
        marker in normalized
        for marker in (
            "10-k",
            "10-q",
            "annual report",
            "quarterly report",
            "filing",
            "risk factor",
            "business risk",
            "management commentary",
        )
    )


def _plan_branch_references(branch: ExecutionBranch) -> set[str]:
    references = set(branch.depends_on)
    if isinstance(branch, CalculationBranch):
        references.update(branch.input_refs)
    if isinstance(branch, ChartBranch):
        references.add(branch.dataset_ref)
    return references


__all__ = (
    "_constrain_plan_sources",
    "_ensure_required_growth_calculations",
)
