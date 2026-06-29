from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _reconcile_analysis_with_plan(
    analysis: QuestionAnalysis,
    plan: ExecutionPlan,
) -> QuestionAnalysis:
    """Make a concrete supported plan authoritative over an inconsistent model classification."""

    represented = _represented_capabilities(plan)
    if (
        not DETERMINISTIC_PLAN_REASON_CODES.isdisjoint(plan.reason_codes)
        and plan.route is not ResearchRoute.UNSUPPORTED
    ):
        return _analysis_for_represented_plan(
            analysis,
            plan,
            represented,
        )
    if (
        analysis.route is not ResearchRoute.UNSUPPORTED
        and plan.route is not ResearchRoute.UNSUPPORTED
        and set(analysis.required_capabilities).issubset(represented)
    ):
        return _analysis_for_represented_plan(
            analysis,
            plan,
            represented,
        )
    if (
        analysis.route in {ResearchRoute.UNSUPPORTED, ResearchRoute.HYBRID}
        or plan.route is ResearchRoute.UNSUPPORTED
        or analysis.chart_requested
        or AgentCapability.CHART in analysis.required_capabilities
    ):
        return analysis
    return _analysis_for_represented_plan(analysis, plan, represented)


def _analysis_for_represented_plan(
    analysis: QuestionAnalysis,
    plan: ExecutionPlan,
    represented: set[AgentCapability],
) -> QuestionAnalysis:
    ordered_capabilities = tuple(
        capability for capability in AgentCapability if capability in represented
    )
    chart_requested = AgentCapability.CHART in represented
    if (
        analysis.route is plan.route
        and analysis.required_capabilities == ordered_capabilities
        and analysis.chart_requested is chart_requested
    ):
        return analysis
    return analysis.model_copy(
        update={
            "route": plan.route,
            "required_capabilities": ordered_capabilities,
            "chart_requested": chart_requested,
            "reason_codes": tuple(
                dict.fromkeys((*analysis.reason_codes, "reconciled_to_valid_plan"))
            ),
        }
    )


def _canonicalize_plan_route(plan: ExecutionPlan) -> ExecutionPlan:
    """Derive route semantics from concrete source and calculation branches."""

    source_kinds = {item.kind for item in _source_branches(plan)}
    has_calculation = any(isinstance(item, CalculationBranch) for item in plan.branches)
    route: ResearchRoute | None = None
    if len(source_kinds) >= 2:
        route = ResearchRoute.HYBRID
    elif has_calculation:
        route = ResearchRoute.CALCULATION
    elif source_kinds == {"retrieve_documents"}:
        route = ResearchRoute.RAG_ONLY
    elif source_kinds == {"query_financial_facts"}:
        route = ResearchRoute.STRUCTURED_ONLY
    elif source_kinds == {"query_macro_series"}:
        route = ResearchRoute.API_ONLY
    if route is None or route is plan.route:
        return plan
    return plan.model_copy(update={"route": route})


def _domain_execution_plan(model_plan: ModelExecutionPlan) -> ExecutionPlan:
    branches: list[ExecutionBranch] = []
    for item in model_plan.branches:
        branches.append(_domain_execution_branch(item))
    return ExecutionPlan(
        route=model_plan.route,
        branches=tuple(branches),
        requires_citations=model_plan.requires_citations,
        reason_codes=model_plan.reason_codes,
    )


def _domain_execution_branch(item: ModelExecutionBranch) -> ExecutionBranch:
    if item.kind == "retrieve_documents":
        if item.retrieval_request is None:
            raise ValueError("Retrieval branch requires retrieval_request.")
        return DocumentRetrievalBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            request=item.retrieval_request,
        )
    if item.kind == "query_financial_facts":
        if item.financial_request is None:
            raise ValueError("Financial branch requires financial_request.")
        return FinancialFactsBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            request=item.financial_request,
        )
    if item.kind == "query_macro_series":
        if item.macro_request is None:
            raise ValueError("Macro branch requires macro_request.")
        return MacroSeriesBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            request=item.macro_request,
        )
    if item.kind == "calculate_metrics":
        if item.operation is None:
            raise ValueError("Calculation branch requires operation.")
        return CalculationBranch(
            branch_id=item.branch_id,
            depends_on=item.depends_on,
            optional=item.optional,
            operation=item.operation,
            input_refs=item.input_refs,
            years=Decimal(str(item.years)) if item.years is not None else None,
            window=item.window,
            base=Decimal(str(item.base)),
        )
    dataset_ref = item.dataset_ref or (item.depends_on[0] if item.depends_on else None)
    if dataset_ref is None:
        raise ValueError("Chart branch requires a dataset reference or dependency.")
    return ChartBranch(
        branch_id=item.branch_id,
        depends_on=item.depends_on,
        optional=item.optional,
        chart_type=item.chart_type or "line",
        dataset_ref=dataset_ref,
        title=item.title or "Research chart",
        x_label=item.x_label,
    )


def _validate_single_series_request(
    branch: FinancialFactsBranch | MacroSeriesBranch,
) -> None:
    if isinstance(branch, MacroSeriesBranch):
        if len(branch.request.series_ids) != 1:
            raise ValueError("Numeric macro branches must select exactly one series.")
        return
    company_selectors = len(branch.request.company_ids) + len(branch.request.tickers)
    if len(branch.request.metrics) != 1 or company_selectors != 1:
        raise ValueError("Numeric financial branches must select one company and one metric.")


def _validate_route_shape(plan: ExecutionPlan) -> None:
    source_kinds = {item.kind for item in _source_branches(plan)}
    if plan.route is ResearchRoute.UNSUPPORTED:
        if plan.branches:
            raise ValueError("Unsupported plans must be empty.")
        return
    if not source_kinds:
        raise ValueError("Supported plans require a source branch.")
    if plan.route is ResearchRoute.RAG_ONLY and source_kinds != {"retrieve_documents"}:
        raise ValueError("RAG-only plans may only retrieve documents.")
    if plan.route is ResearchRoute.STRUCTURED_ONLY and source_kinds != {"query_financial_facts"}:
        raise ValueError("Structured-only plans require financial facts.")
    if plan.route is ResearchRoute.API_ONLY and source_kinds != {"query_macro_series"}:
        raise ValueError("API-only plans require macro series.")
    if plan.route is ResearchRoute.CALCULATION and not any(
        isinstance(item, CalculationBranch) for item in plan.branches
    ):
        raise ValueError("Calculation routes require a calculation branch.")
    if plan.route is ResearchRoute.HYBRID and len(source_kinds) < 2:
        raise ValueError("Hybrid plans require at least two source kinds.")


def _represented_capabilities(plan: ExecutionPlan) -> set[AgentCapability]:
    represented: set[AgentCapability] = set()
    mapping = {
        "retrieve_documents": AgentCapability.DOCUMENTS,
        "query_financial_facts": AgentCapability.FINANCIAL_FACTS,
        "query_macro_series": AgentCapability.MACRO_SERIES,
        "calculate_metrics": AgentCapability.CALCULATIONS,
        "generate_chart_spec": AgentCapability.CHART,
    }
    for branch in plan.branches:
        represented.add(mapping[branch.kind])
    return represented

__all__ = ('_reconcile_analysis_with_plan', '_analysis_for_represented_plan', '_canonicalize_plan_route', '_domain_execution_plan', '_domain_execution_branch', '_validate_single_series_request', '_validate_route_shape', '_represented_capabilities')  # noqa: E501
