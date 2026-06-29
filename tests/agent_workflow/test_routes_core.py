from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_hybrid_source_branches_run_concurrently_and_merge_stably() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue and rates",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
        ),
        reason_codes=("financial_macro_comparison",),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.HYBRID,
        branches=(_financial_branch(), _macro_branch()),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(
            "Revenue was 125 USD [financial_fact:22222222-2222-2222-2222-222222222222] "
            "and the rate was 3.5 percent [macro:fedfunds:2025-12-01].",
        ),
    )
    tools = FakeResearchTools(synchronize_sources=True)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Compare revenue and rates", session_id="session-1"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["tool_calls_used"] == 2
    assert len(tools.thread_ids) == 2
    assert [item.evidence_id for item in result["evidence"]] == sorted(
        item.evidence_id for item in result["evidence"]
    )
    assert len(result["citations"]) == 2


def test_rag_only_route_uses_document_retrieval() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What risks did Cloudflare report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(query="Cloudflare business risks"),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What risks did Cloudflare report?", session_id="session-rag"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["retrieval"] == 1
    answer_messages = next(
        messages for purpose, messages in model.model_calls if purpose is ModelPurpose.ANSWER
    )
    assert "untrusted data" in answer_messages[0].content
    assert '"trust": "untrusted_external_data"' in answer_messages[1].content


def test_previous_chart_period_question_answers_from_session_memory_without_rag() -> None:
    analysis = QuestionAnalysis(
        normalized_question="what period was that chart and how many reports",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
        chart_requested=False,
        is_follow_up=True,
        reason_codes=(
            "follow_up_about_previous_output",
            "asks_about_covered_period",
            "asks_about_number_of_reports",
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="previous_chart_context",
                    request=AdaptiveRetrievalRequest(query="Find the previous chart output"),
                ),
            ),
        ),
    )
    older_artifact = SessionArtifactContext(
        artifact_id="chart:older",
        run_id=uuid.uuid4(),
        user_question="Plot Cloudflare revenue growth.",
        title="Cloudflare revenue growth",
        chart_type="line",
        series_labels=("Cloudflare, Inc. revenue YoY",),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
        calculations=("year_over_year_growth",),
        period_start=date(2023, 9, 30),
        period_end=date(2026, 3, 31),
        point_count=8,
        source_branch_ids=("cloudflare_revenue",),
    )
    latest_artifact = SessionArtifactContext(
        artifact_id="chart:latest",
        run_id=uuid.uuid4(),
        user_question="а тепер додай туди ще і Apple",
        title="Revenue growth comparison",
        chart_type="line",
        series_labels=(
            "Apple Inc. revenue YoY",
            "Cloudflare, Inc. revenue YoY",
            "Tesla, Inc. revenue YoY",
        ),
        company_ids=(APPLE_ID, COMPANY_ID, NETFLIX_ID),
        metrics=("revenue",),
        calculations=("year_over_year_growth",),
        period_start=date(2024, 3, 31),
        period_end=date(2024, 12, 31),
        point_count=4,
        source_branch_ids=("apple_revenue", "cloudflare_revenue", "tesla_revenue"),
    )
    state = create_initial_agent_state(
        "це був графік за який період? скільки там останніх репортів?",
        session_id="session-previous-chart-period",
    )
    state["session_memory"] = SessionMemory(
        recent_artifacts=(older_artifact, latest_artifact),
    )
    tools = FakeResearchTools()

    result = build_research_graph().invoke(
        state,
        config={"recursion_limit": 24},
        context=ResearchAgentRuntime(model, tools),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "2024-03-31" in result["final_answer"]
    assert "2024-12-31" in result["final_answer"]
    assert "2026-03-31" not in result["final_answer"]
    assert "4 точок" in result["final_answer"]
    assert "Apple Inc. revenue YoY" in result["final_answer"]
    assert tools.calls["resolve"] == 0
    assert tools.calls["retrieval"] == 0
    assert model.purposes == [ModelPurpose.PARSE]
    assert result["branch_outcomes"] == ()
