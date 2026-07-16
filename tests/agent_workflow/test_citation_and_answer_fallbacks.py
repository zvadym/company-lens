from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_invalid_citation_is_repaired_once() -> None:
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
        texts=(
            "Revenue was 125 USD [invented:evidence].",
            "Revenue was 125 USD [financial_fact:22222222-2222-2222-2222-222222222222].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was revenue?", session_id="session-3"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 1
    assert ModelPurpose.REPAIR in model.purposes
    assert result["answer_validation"].valid is True
    repair_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.REPAIR
    )
    assert '"payload"' not in repair_context
    assert "financial_fact:22222222-2222-2222-2222-222222222222" in repair_context


def test_invalid_repair_falls_back_to_deterministic_cited_summary() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(_financial_branch(),),
    )
    invalid_answer = f"Cloudflare revenue was 124.6 USD [financial_fact:{FACT_ID}]."
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(invalid_answer, invalid_answer),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was Cloudflare revenue?",
        session_id="session-invalid-repair-fallback",
        policy=ExecutionPolicy(max_repair_attempts=1),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 1
    assert result["answer_validation"].valid is True
    assert "125 USD" in result["final_answer"]
    assert "124.6" not in result["final_answer"]
    assert model.purposes.count(ModelPurpose.REPAIR) == 1


def test_invalid_hybrid_repair_falls_back_to_cited_mixed_evidence() -> None:
    class MixedEvidenceTools(AnnualSeriesFinancialTools):
        def retrieve_documents(
            self,
            request: AdaptiveRetrievalRequest,
        ) -> AdaptiveRetrievalResponse:
            response = super().retrieve_documents(request)
            context = response.context[0].model_copy(
                update={
                    "content": (
                        "Cloudflare identified competition as a material business risk. "
                        "Cloudflare also identified rapid technological change as a risk."
                    ),
                    "token_count": 18,
                }
            )
            return response.model_copy(update={"context": (context,)})

    analysis = QuestionAnalysis(
        normalized_question="Compare revenue growth with reported risks.",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.DOCUMENTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.HYBRID,
        branches=(
            _financial_branch(),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
            DocumentRetrievalBranch(
                branch_id="documents",
                request=AdaptiveRetrievalRequest(query="Cloudflare risks"),
            ),
        ),
    )
    invalid_answer = f"Cloudflare revenue was 999 USD [financial_fact:{FACT_ID}]."
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(invalid_answer, invalid_answer),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, MixedEvidenceTools())).run(
        "Compare Cloudflare revenue growth with reported risks.",
        session_id="session-invalid-hybrid-repair-fallback",
        policy=ExecutionPolicy(max_repair_attempts=1),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert "[calculation:growth]" in result["final_answer"]
    assert "[document:cloudflare-risk]" in result["final_answer"]
    assert all(claim.evidence_ids for claim in result["claims"] if claim.material)


def test_repair_timeout_is_not_retried_by_general_node_policy() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    model = RepairTimeoutModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(_financial_branch(),),
        ),
        texts=("Revenue was 125 USD [invented:evidence].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was revenue?",
        session_id="session-repair-timeout",
        policy=ExecutionPolicy(max_retries_per_node=2),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert result["final_answer"] is not None
    assert "125 USD" in result["final_answer"]
    assert model.purposes.count(ModelPurpose.REPAIR) == 1
    assert any(error.code == "openai_timeout" for error in result["errors"])


def test_answer_timeout_falls_back_to_deterministic_cited_summary() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            _financial_branch(),
            CalculationBranch(
                branch_id="growth",
                operation="percentage_change",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = AnswerTimeoutModelProvider(analysis=analysis, plan=plan)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Compare Cloudflare revenue growth.",
        session_id="session-answer-timeout-fallback",
        policy=ExecutionPolicy(max_retries_per_node=1),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "[calculation:growth]" in result["final_answer"]
    assert "\n\n| Period | Company | Metric | Value |" in result["final_answer"]
    assert result["answer_validation"].valid is True
    assert any(error.code == "openai_timeout" for error in result["errors"])


def test_answer_timeout_fallback_formats_multi_point_calculations() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            _financial_branch(),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = AnswerTimeoutModelProvider(analysis=analysis, plan=plan)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, AnnualSeriesFinancialTools())).run(
        "Compare Cloudflare revenue growth.",
        session_id="session-answer-timeout-series-fallback",
        policy=ExecutionPolicy(max_retries_per_node=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "latest value was 25% at 2025-12-31" in result["final_answer"]
    assert "[calculation:growth]" in result["final_answer"]
    assert "[{'label':" not in result["final_answer"]
    assert "'observed_at':" not in result["final_answer"]
    assert result["answer_validation"].valid is True
