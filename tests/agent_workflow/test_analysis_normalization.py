from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *
from company_lens.agent.workflow import _domain_question_analysis


def test_hybrid_growth_analysis_infers_missing_calculation_capability() -> None:
    analysis = _domain_question_analysis(
        ModelQuestionAnalysis(
            normalized_question=(
                "Compare Datadog revenue growth with the principal risks reported for 2024."
            ),
            route=ResearchRoute.HYBRID,
            required_capabilities=(
                AgentCapability.DOCUMENTS,
                AgentCapability.FINANCIAL_FACTS,
            ),
            reason_codes=("mentions_revenue_growth",),
        )
    )

    assert analysis.route is ResearchRoute.HYBRID
    assert analysis.required_capabilities == (
        AgentCapability.DOCUMENTS,
        AgentCapability.FINANCIAL_FACTS,
        AgentCapability.CALCULATIONS,
    )
    assert "calculation_capability_inferred" in analysis.reason_codes


def test_document_only_growth_language_does_not_infer_numeric_calculation() -> None:
    analysis = _domain_question_analysis(
        ModelQuestionAnalysis(
            normalized_question="What risks could slow Datadog revenue growth?",
            route=ResearchRoute.RAG_ONLY,
            required_capabilities=(AgentCapability.DOCUMENTS,),
            reason_codes=("risk_factors",),
        )
    )

    assert analysis.route is ResearchRoute.RAG_ONLY
    assert analysis.required_capabilities == (AgentCapability.DOCUMENTS,)
    assert "calculation_capability_inferred" not in analysis.reason_codes
