from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_parse_failure_uses_follow_up_replay_analysis_for_same_data_chart() -> None:
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    previous_resolved = ResolvedQuery(
        query="plot microsoft revenue growth",
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_resolved,
        recent_resolved_queries=(previous_resolved,),
        last_execution_plan=previous_plan,
    )
    model = ParseFailureModelProvider(
        analysis=QuestionAnalysis(
            normalized_question="unused",
            route=ResearchRoute.UNSUPPORTED,
        ),
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
    )
    state = create_initial_agent_state(
        "Побудуй bar chart на цих самих даних",
        session_id="session-parse-fallback-same-data",
    )
    state["session_memory"] = memory

    parse_update = _parse_question(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert "status" not in parse_update
    assert "errors" not in parse_update
    analysis = parse_update["analysis"]
    assert isinstance(analysis, QuestionAnalysis)
    assert analysis.is_follow_up is True
    assert analysis.chart_requested is True
    assert analysis.route is ResearchRoute.CALCULATION
    assert "chart_type_override" in analysis.reason_codes

    state.update(parse_update)
    merged = _merge_follow_up_if_needed(
        ResolvedQuery(
            query="Побудуй bar chart на цих самих даних",
            metrics=("revenue",),
        ),
        analysis,
        memory,
    )
    state["resolved_query"] = merged
    plan_update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert ModelPurpose.PLAN not in model.purposes
    plan = plan_update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "bar"


def test_follow_up_replays_previous_chart_with_chart_type_override() -> None:
    analysis = QuestionAnalysis(
        normalized_question="build a bar chart from the same data",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "same_data", "chart_type_override"),
    )
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    previous_resolved = ResolvedQuery(
        query="plot microsoft revenue growth",
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_resolved,
        recent_resolved_queries=(previous_resolved,),
        last_execution_plan=previous_plan,
    )
    merged = _merge_follow_up_if_needed(
        ResolvedQuery(query="build a bar chart from the same data", metrics=("revenue",)),
        analysis,
        memory,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "build a bar chart from the same data",
        session_id="session-replay-chart-type",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    assert merged.company_ids == (MICROSOFT_ID,)
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "bar"
    assert chart.depends_on == ("replay_1_revenue_calc",)


def test_follow_up_replays_add_company_bar_chart_without_dropping_previous_company() -> None:
    analysis = QuestionAnalysis(
        normalized_question="додай amazon і побудуй bar chart",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "adds_company", "explicit_chart_request"),
    )
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    previous_resolved = ResolvedQuery(
        query="побудуй графік росту revenue microsoft",
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_resolved,
        recent_resolved_queries=(previous_resolved,),
        last_execution_plan=previous_plan,
    )
    merged = _merge_follow_up_if_needed(
        ResolvedQuery(
            query="додай amazon і побудуй bar chart",
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
                            display_value="AMAZON COM INC",
                            match_kind="sec_company_extracted",
                        ),
                    ),
                ),
            ),
            company_ids=(AMAZON_ID,),
            metrics=("revenue",),
        ),
        analysis,
        memory,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "додай amazon і побудуй bar chart",
        session_id="session-replay-add-company-bar-chart",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    assert merged.company_ids == (MICROSOFT_ID, AMAZON_ID)
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "errors" not in update
    assert [
        branch.request.company_ids
        for branch in plan.branches
        if isinstance(branch, FinancialFactsBranch)
    ] == [(MICROSOFT_ID,), (AMAZON_ID,)]
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "bar"
    assert chart.depends_on == ("replay_1_revenue_calc", "replay_2_revenue_calc")
