from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *
from company_lens.agent.workflow import (
    _domain_execution_plan,
    _normalize_and_validate_plan,
)


def test_source_dataset_alias_is_canonicalized_in_calculation_references() -> None:
    raw_plan = ModelExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            ModelExecutionBranch(
                kind="query_financial_facts",
                branch_id="revenue_last_five_quarters",
                dataset_ref="revenue_qoq_input",
                financial_request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    period_types=("quarter",),
                    limit=5,
                ),
            ),
            ModelExecutionBranch(
                kind="calculate_metrics",
                branch_id="revenue_qoq_growth",
                depends_on=("revenue_last_five_quarters",),
                operation="quarter_over_quarter_growth",
                input_refs=("revenue_qoq_input",),
                window=4,
            ),
        ),
        requires_citations=False,
    )

    plan = _domain_execution_plan(raw_plan)
    normalized = _normalize_and_validate_plan(
        plan,
        _growth_analysis(),
        _growth_query(),
        ExecutionPolicy(),
        retrieval_index_name="test-index",
        retrieval_index_version="v1",
    )

    calculation = next(
        branch for branch in normalized.branches if isinstance(branch, CalculationBranch)
    )
    assert calculation.input_refs == ("revenue_last_five_quarters",)
    assert calculation.depends_on == ("revenue_last_five_quarters",)


def test_source_dataset_alias_is_canonicalized_in_chart_reference() -> None:
    raw_plan = ModelExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(
            ModelExecutionBranch(
                kind="query_financial_facts",
                branch_id="revenue_quarters",
                dataset_ref="chart_input",
                financial_request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    period_types=("quarter",),
                    limit=4,
                ),
            ),
            ModelExecutionBranch(
                kind="generate_chart_spec",
                branch_id="revenue_chart",
                depends_on=("revenue_quarters",),
                dataset_ref="chart_input",
                chart_type="line",
                title="Quarterly revenue",
            ),
        ),
    )

    plan = _domain_execution_plan(raw_plan)

    chart = next(branch for branch in plan.branches if isinstance(branch, ChartBranch))
    assert chart.dataset_ref == "revenue_quarters"
    assert chart.depends_on == ("revenue_quarters",)


def test_duplicate_source_dataset_alias_is_rejected() -> None:
    financial_request = FinancialFactQuery(
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    raw_plan = ModelExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            ModelExecutionBranch(
                kind="query_financial_facts",
                branch_id="first_revenue",
                dataset_ref="revenue_input",
                financial_request=financial_request,
            ),
            ModelExecutionBranch(
                kind="query_financial_facts",
                branch_id="second_revenue",
                dataset_ref="revenue_input",
                financial_request=financial_request,
            ),
        ),
    )

    with pytest.raises(ValueError, match="Duplicate source dataset alias"):
        _domain_execution_plan(raw_plan)


def test_unknown_calculation_reference_is_a_validation_error() -> None:
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="revenue_quarters",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    period_types=("quarter",),
                    limit=5,
                ),
            ),
            CalculationBranch(
                branch_id="revenue_growth",
                depends_on=("revenue_quarters",),
                operation="quarter_over_quarter_growth",
                input_refs=("unknown_input",),
            ),
        ),
    )

    with pytest.raises(ValueError, match="Unknown calculation input reference"):
        _normalize_and_validate_plan(
            plan,
            _growth_analysis(),
            _growth_query(),
            ExecutionPolicy(),
            retrieval_index_name="test-index",
            retrieval_index_version="v1",
        )


def _growth_analysis() -> QuestionAnalysis:
    return QuestionAnalysis(
        normalized_question=(
            "show cloudflare quarter-over-quarter revenue growth over the last four quarters"
        ),
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        reason_codes=("qoq_growth_requested", "last_four_quarters_requested"),
    )


def _growth_query() -> ResolvedQuery:
    return ResolvedQuery(
        query="Show Cloudflare quarter-over-quarter revenue growth over the last four quarters.",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
