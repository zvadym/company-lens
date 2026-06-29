from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_planner_receives_recent_artifact_timeline_context() -> None:
    analysis = QuestionAnalysis(
        normalized_question="build the same chart again",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "same_chart"),
    )
    facts = FinancialFactsBranch(
        branch_id="revenue",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            fiscal_years=(2023, 2024, 2025),
        ),
    )
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref=growth.branch_id,
        depends_on=(growth.branch_id,),
        title="Revenue growth",
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth, chart)),
    )
    state = create_initial_agent_state(
        "побудуй такий графік ще раз",
        session_id="session-artifact-planner-context",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="побудуй такий графік ще раз",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(
        recent_artifacts=(
            SessionArtifactContext(
                artifact_id="chart:first",
                run_id=uuid.uuid4(),
                user_question="Plot Cloudflare revenue growth.",
                title="Revenue growth",
                chart_type="line",
                series_labels=("Cloudflare revenue YoY",),
                company_ids=(COMPANY_ID,),
                metrics=("revenue",),
                calculations=("year_over_year_growth",),
                period_start=date(2023, 9, 30),
                period_end=date(2026, 3, 31),
                point_count=8,
                source_branch_ids=("revenue",),
            ),
            SessionArtifactContext(
                artifact_id="chart:second",
                run_id=uuid.uuid4(),
                user_question="Add Tesla.",
                title="Peer revenue growth",
                chart_type="line",
                series_labels=("Cloudflare revenue YoY", "Tesla revenue YoY"),
                company_ids=(COMPANY_ID, NETFLIX_ID),
                metrics=("revenue",),
                calculations=("year_over_year_growth",),
                period_start=date(2024, 9, 30),
                period_end=date(2026, 3, 31),
                point_count=5,
                source_branch_ids=("cloudflare_revenue", "tesla_revenue"),
            ),
        )
    )

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert "execution_plan" in update
    plan_messages = next(
        messages for purpose, messages in model.model_calls if purpose is ModelPurpose.PLAN
    )
    context = json.loads(plan_messages[1].content)
    assert context["research_frame"]["company_targets"][0]["company_id"] == str(COMPANY_ID)
    assert context["research_frame"]["financial_readiness"][0]["status"] == "available"
    assert [artifact["artifact_id"] for artifact in context["recent_artifacts"]] == [
        "chart:first",
        "chart:second",
    ]
    assert context["recent_artifacts"][1]["period"] == {
        "start": "2024-09-30",
        "end": "2026-03-31",
        "point_count": 5,
    }
    assert context["recent_artifacts"][1]["series_labels"] == [
        "Cloudflare revenue YoY",
        "Tesla revenue YoY",
    ]
