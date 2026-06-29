from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_add_series_follow_up_uses_legacy_last_resolved_query_memory() -> None:
    cloudflare = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    amazon = ResolvedQuery(
        query="add Amazon to that chart",
        entities=(
            EntityResolution(
                kind="company",
                mention="amazon",
                status="resolved",
                canonical_value=str(AMAZON_ID),
                candidates=(
                    EntityCandidate(
                        id=AMAZON_ID,
                        canonical_value=str(AMAZON_ID),
                        display_value="Amazon.com, Inc.",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(AMAZON_ID,),
    )
    analysis = QuestionAnalysis(
        normalized_question="add Amazon to the existing comparison chart",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "add_series", "comparison_chart"),
    )
    memory = SessionMemory(last_resolved_query=cloudflare)

    merged = _merge_follow_up_if_needed(amazon, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, AMAZON_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "amazon",
        "cloudflare",
    ]
    assert merged.metrics == ("revenue",)


def test_add_series_follow_up_plan_accepts_previous_and_new_company_ids() -> None:
    analysis = QuestionAnalysis(
        normalized_question="add Apple to the existing comparison chart",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "add_series", "comparison_chart"),
    )
    cloudflare = ResolvedQuery(
        query="Plot Cloudflare revenue growth.",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    previous_chart = ResolvedQuery(
        query="а тепер на графік виведи обидва",
        company_ids=(NETFLIX_ID, COMPANY_ID),
        metrics=("revenue",),
    )
    apple = ResolvedQuery(
        query="а тепер додай туди ще і Apple",
        entities=(
            EntityResolution(
                kind="company",
                mention="apple",
                status="resolved",
                canonical_value=str(APPLE_ID),
            ),
        ),
        company_ids=(APPLE_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_chart,
        recent_resolved_queries=(cloudflare, previous_chart),
    )
    merged = _merge_follow_up_if_needed(apple, analysis, memory)
    branches: list[FinancialFactsBranch | CalculationBranch | ChartBranch] = []
    growth_refs: list[str] = []
    for index, company_id in enumerate(merged.company_ids, start=1):
        facts_id = f"company_{index}_revenue"
        growth_id = f"company_{index}_growth"
        branches.append(
            FinancialFactsBranch(
                branch_id=facts_id,
                request=FinancialFactQuery(
                    company_ids=(company_id,),
                    metrics=("revenue",),
                ),
            )
        )
        branches.append(
            CalculationBranch(
                branch_id=growth_id,
                operation="year_over_year_growth",
                input_refs=(facts_id,),
                depends_on=(facts_id,),
            )
        )
        growth_refs.append(growth_id)
    branches.append(
        ChartBranch(
            branch_id="comparison_chart",
            chart_type="line",
            dataset_ref=growth_refs[0],
            depends_on=tuple(growth_refs),
            title="Revenue growth comparison",
        )
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=tuple(branches)),
    )
    state = create_initial_agent_state(
        "а тепер додай туди ще і Apple",
        session_id="session-add-series-plan-validation",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "errors" not in update
    planned_company_ids = [
        branch.request.company_ids
        for branch in plan.branches
        if isinstance(branch, FinancialFactsBranch)
    ]
    assert planned_company_ids == [
        (COMPANY_ID,),
        (NETFLIX_ID,),
        (APPLE_ID,),
    ]
