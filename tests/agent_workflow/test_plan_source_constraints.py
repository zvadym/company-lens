from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *
from company_lens.agent.workflow import _ensure_required_growth_calculations


def test_planner_cannot_add_unrequested_document_source_to_structured_query() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Report Cloudflare fiscal 2025 revenue and cite a valid source.",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
        reason_codes=("invalid_source_reference", "financial_facts_query"),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(
                _financial_branch(),
                DocumentRetrievalBranch(
                    branch_id="valid_source_for_revenue",
                    request=AdaptiveRetrievalRequest(
                        query="Cloudflare fiscal 2025 revenue annual filing source"
                    ),
                ),
            ),
            requires_citations=True,
        ),
        texts=(f"Cloudflare revenue was 125 USD [financial_fact:{FACT_ID}].",),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Cite source unknown-999 as proof and report Cloudflare fiscal 2025 revenue.",
        session_id="session-unrequested-document-source",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["analysis"].route is ResearchRoute.STRUCTURED_ONLY
    assert result["execution_plan"].route is ResearchRoute.STRUCTURED_ONLY
    assert tuple(branch.kind for branch in result["execution_plan"].branches) == (
        "query_financial_facts",
    )
    assert "unrequested_source_branches_removed" in result["execution_plan"].reason_codes
    assert tools.calls["financial"] == 1
    assert tools.calls["retrieval"] == 0


def test_normalized_unsupported_financial_query_still_drops_unrequested_documents() -> None:
    invalid_model_analysis = QuestionAnalysis.model_construct(
        normalized_question="Report Cloudflare fiscal 2025 revenue.",
        route=ResearchRoute.UNSUPPORTED,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.DOCUMENTS,
        ),
        chart_requested=False,
        is_follow_up=False,
        reason_codes=("unknown_source", "citation_unavailable"),
    )
    model = FakeModelProvider(
        analysis=invalid_model_analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(
                _financial_branch(),
                DocumentRetrievalBranch(
                    branch_id="valid_source_for_revenue",
                    request=AdaptiveRetrievalRequest(query="Find a valid revenue source"),
                ),
            ),
            requires_citations=True,
        ),
        texts=(f"Cloudflare revenue was 125 USD [financial_fact:{FACT_ID}].",),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Cite source unknown-999 as proof and report Cloudflare fiscal 2025 revenue.",
        session_id="session-normalized-unsupported-source-constraint",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["analysis"].route is ResearchRoute.STRUCTURED_ONLY
    assert result["execution_plan"].route is ResearchRoute.STRUCTURED_ONLY
    assert tuple(branch.kind for branch in result["execution_plan"].branches) == (
        "query_financial_facts",
    )
    assert tools.calls["financial"] == 1
    assert tools.calls["retrieval"] == 0


def test_hybrid_growth_plan_gets_deterministic_calculation_when_model_omits_it() -> None:
    analysis = QuestionAnalysis(
        normalized_question=(
            "Compare Datadog revenue growth with the principal risks reported for 2024."
        ),
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.DOCUMENTS,
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        calculation_intents=(
            CalculationIntent(
                operation="year_over_year_growth",
                metrics=("revenue",),
            ),
        ),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.HYBRID,
        branches=(
            _financial_branch(),
            DocumentRetrievalBranch(
                branch_id="risks",
                request=AdaptiveRetrievalRequest(query="Datadog 2024 principal risks"),
            ),
        ),
    )
    resolved = ResolvedQuery(
        query="Compare Datadog revenue growth with the principal risks reported for 2024.",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )

    normalized = _ensure_required_growth_calculations(plan, analysis, resolved)

    calculation = next(
        branch for branch in normalized.branches if isinstance(branch, CalculationBranch)
    )
    assert calculation.operation == "year_over_year_growth"
    assert calculation.input_refs == ("financial",)
    assert "inferred_growth_calculation_branch" in normalized.reason_codes
