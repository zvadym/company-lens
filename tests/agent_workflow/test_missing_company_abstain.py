from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_financial_chart_without_company_abstains_before_planning() -> None:
    class NoCompanyTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

    analysis = QuestionAnalysis(
        normalized_question="Plot revenue growth against the federal funds rate",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.HYBRID, branches=(_financial_branch(),)),
    )
    tools = NoCompanyTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Plot revenue growth against the federal funds rate.",
        session_id="session-missing-company",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert any(error.code == "missing_company" for error in result["errors"])
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls["financial"] == 0
    assert tools.calls["macro"] == 0


def test_unresolved_follow_up_company_abstain_has_user_facing_answer() -> None:
    class UnresolvedSamsungTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(
                query=query,
                entities=(
                    EntityResolution(
                        kind="public_company",
                        mention="SAMSUNG",
                        status="unresolved",
                    ),
                ),
                metrics=("revenue",),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Samsung revenue growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="SAMSUNG"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = UnresolvedSamsungTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "а тепер те саме для SAMSUNG",
        session_id="session-missing-follow-up-company",
    )

    frame = cast(ResearchFrame, result["research_frame"])
    assert result["status"] is AgentRunStatus.ABSTAINED
    assert any(error.code == "missing_company" for error in result["errors"])
    assert result["final_answer"] is not None
    assert "SAMSUNG" in result["final_answer"]
    assert "SEC/EDGAR" in result["final_answer"]
    assert "попередній компанії" in result["final_answer"]
    assert "ticker" in result["final_answer"]
    assert frame.company_targets[0].mention == "SAMSUNG"
    assert frame.company_targets[0].source == "current_question"
    assert not frame.inherited_from_previous
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls["prepare"] == 0
    assert tools.calls["financial"] == 0
