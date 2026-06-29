from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_recoverable_tool_failure_retries_within_global_call_budget() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(_financial_branch(),),
        ),
        texts=("Revenue was 125 USD [financial_fact:22222222-2222-2222-2222-222222222222].",),
    )
    tools = FlakyFinancialTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What was revenue?",
        session_id="session-retry",
        policy=ExecutionPolicy(max_tool_calls=2, max_retries_per_node=2),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 2
    assert result["tool_calls_used"] == 2


def test_optional_branch_failure_produces_partial_answer() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue with rates if available",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(_financial_branch(), _macro_branch().model_copy(update={"optional": True})),
        ),
        texts=(
            "Revenue was 125 USD; macro data was unavailable "
            "[financial_fact:22222222-2222-2222-2222-222222222222].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, BrokenMacroTools())).run(
        "Compare revenue with rates if available", session_id="session-partial"
    )

    assert result["status"] is AgentRunStatus.PARTIAL
    assert result["final_answer"] is not None
    assert any(error.code == "macro_unavailable" for error in result["errors"])


def test_unsupported_question_abstains_without_answer_generation() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Write a poem",
        route=ResearchRoute.UNSUPPORTED,
        reason_codes=("outside_research_scope",),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Write a poem", session_id="session-4"
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert result["final_answer"] is None
    assert ModelPurpose.ANSWER not in model.purposes
    assert result["tool_calls_used"] == 0


def test_parse_failure_abstains_with_explanation_and_rewrites() -> None:
    model = ParseFailureModelProvider(
        analysis=QuestionAnalysis(
            normalized_question="unused",
            route=ResearchRoute.UNSUPPORTED,
        ),
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Plot Cloudflare revenue growth against the Netflix",
        session_id="session-parse-failure",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert result["final_answer"] is not None
    assert "could not classify the request" in result["final_answer"]
    assert "Unexpected OpenAI provider failure." not in result["final_answer"]
    assert (
        "Plot Cloudflare revenue growth against Netflix revenue growth." in result["final_answer"]
    )
    assert any(error.code == "openai_unexpected" for error in result["errors"])
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls == {}
    assert result["tool_calls_used"] == 0


def test_over_budget_plan_fails_before_source_calls() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue and rates",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(_financial_branch(), _macro_branch()),
        ),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Compare revenue and rates",
        session_id="session-5",
        policy=ExecutionPolicy(max_tool_calls=1),
    )

    assert result["status"] is AgentRunStatus.FAILED
    assert tools.calls["financial"] == 0
    assert tools.calls["macro"] == 0
    assert any(error.code == "invalid_execution_plan" for error in result["errors"])
