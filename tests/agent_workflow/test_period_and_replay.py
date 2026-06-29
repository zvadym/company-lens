from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_period_override_follow_up_reuses_recent_chart_artifact_without_model_plan() -> None:
    analysis = QuestionAnalysis(
        normalized_question="побудуй такий графік за період 2023-2025",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "change_period", "same_chart"),
    )
    artifact = SessionArtifactContext(
        artifact_id="chart:peer_growth",
        run_id=uuid.uuid4(),
        user_question="а тепер додай туди ще і Apple",
        title="Apple vs Cloudflare vs Tesla Revenue Growth",
        chart_type="line",
        series_labels=(
            "Apple Inc. revenue YoY",
            "Cloudflare, Inc. revenue YoY",
            "Tesla, Inc. revenue YoY",
        ),
        company_ids=(APPLE_ID, COMPANY_ID, NETFLIX_ID),
        metrics=("revenue",),
        calculations=("year_over_year_growth",),
        period_start=date(2024, 12, 28),
        period_end=date(2026, 3, 31),
        point_count=5,
        source_branch_ids=("apple_revenue", "cloudflare_revenue", "tesla_revenue"),
    )
    memory = SessionMemory(recent_artifacts=(artifact,))
    current = ResolvedQuery(
        query="побудуй такий графік за період 2023-2025",
        metrics=("revenue",),
    )
    merged = _merge_follow_up_if_needed(current, analysis, memory)
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "побудуй такий графік за період 2023-2025",
        session_id="session-artifact-period-override",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "deterministic_recent_artifact_period_plan" in plan.reason_codes
    financial_branches = [
        branch for branch in plan.branches if isinstance(branch, FinancialFactsBranch)
    ]
    assert [branch.request.company_ids for branch in financial_branches] == [
        (APPLE_ID,),
        (COMPANY_ID,),
        (NETFLIX_ID,),
    ]
    assert all(branch.request.period_start == date(2022, 1, 1) for branch in financial_branches)
    assert all(branch.request.period_end == date(2025, 12, 31) for branch in financial_branches)
    assert [
        branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
    ] == [
        "year_over_year_growth",
        "year_over_year_growth",
        "year_over_year_growth",
    ]
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.title == "Apple vs Cloudflare vs Tesla Revenue Growth"
    assert chart.depends_on == (
        "artifact_1_revenue_growth",
        "artifact_2_revenue_growth",
        "artifact_3_revenue_growth",
    )


def test_follow_up_replays_previous_growth_chart_for_new_company_without_model_plan() -> None:
    analysis = QuestionAnalysis(
        normalized_question="do the same for zoom",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS, AgentCapability.CHART),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "same_chart"),
    )
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "do the same for Zoom",
        session_id="session-replay-new-company",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="do the same for Zoom",
        company_ids=(ZOOM_ID,),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(last_execution_plan=previous_plan)

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "deterministic_follow_up_replay_plan" in plan.reason_codes
    financial_branches = [
        branch for branch in plan.branches if isinstance(branch, FinancialFactsBranch)
    ]
    assert [branch.request.company_ids for branch in financial_branches] == [(ZOOM_ID,)]
    assert [
        branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
    ] == ["year_over_year_growth"]
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "line"
    reconciled = update["analysis"]
    assert isinstance(reconciled, QuestionAnalysis)
    assert reconciled.route is ResearchRoute.CALCULATION
    assert AgentCapability.DOCUMENTS not in reconciled.required_capabilities


def test_follow_up_replay_chart_title_uses_new_series_label() -> None:
    facts = FinancialFactsBranch(
        branch_id="replay_1_revenue_facts",
        request=FinancialFactQuery(company_ids=(ZOOM_ID,), metrics=("revenue",)),
    )
    calculation = CalculationBranch(
        branch_id="replay_1_revenue_calc",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    stale_chart = ChartBranch(
        branch_id="replay_chart",
        chart_type="line",
        dataset_ref=calculation.branch_id,
        depends_on=(calculation.branch_id,),
        title="Microsoft revenue YoY growth - last 8 quarters",
    )
    state = create_initial_agent_state(
        "Зроби те саме для Zoom",
        session_id="session-replay-title",
    )
    state["execution_plan"] = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(facts, calculation, stale_chart),
        reason_codes=("deterministic_follow_up_replay_plan",),
    )
    state["calculations"] = (
        CalculationBranchResult(
            branch_id="replay_1_revenue_calc",
            result=CalculationResult(
                operation="year_over_year_growth",
                values=(
                    CalculationPoint(
                        label="Zoom Communications, Inc. revenue 2026-04-30",
                        value=Decimal("5.47"),
                        observed_at=date(2026, 4, 30),
                    ),
                ),
                inputs=(),
                formula="(current / prior_year - 1) * 100",
                unit="percent",
                sources=("https://sec.example/zoom",),
            ),
        ),
    )
    state["branch_outcomes"] = (
        BranchOutcome(
            branch_id=calculation.branch_id,
            kind=calculation.kind,
            status=BranchStatus.COMPLETED,
            attempts=1,
        ),
    )

    update = _generate_chart_spec(state)

    chart = update["chart_spec"]
    assert chart.title == "Zoom Communications, Inc. revenue YoY"
