from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_answer_generation_uses_human_number_display_values() -> None:
    latest_fact_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

    class LargeNumberFinancialTools(FakeResearchTools):
        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            previous = _financial_observation(
                date(2025, 12, 31), Decimal("81273000000.000000")
            ).model_copy(
                update={
                    "id": uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    "company_id": COMPANY_ID,
                    "company_name": "MICROSOFT CORP",
                    "ticker": "MSFT",
                    "period_type": "quarter",
                    "fiscal_period": "Q4",
                }
            )
            latest = _financial_observation(
                date(2026, 3, 31), Decimal("82886000000.000000")
            ).model_copy(
                update={
                    "id": latest_fact_id,
                    "company_id": COMPANY_ID,
                    "company_name": "MICROSOFT CORP",
                    "ticker": "MSFT",
                    "period_type": "quarter",
                    "fiscal_period": "Q1",
                }
            )
            return FinancialFactQueryResult(
                query=request,
                observations=(previous, latest),
                available_units=("USD",),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Microsoft revenue growth.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="financial",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="percentage_change",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(
            "MICROSOFT CORP revenue was 82886000000.000000 USD "
            f"[financial_fact:{latest_fact_id}]. Revenue growth was "
            "1.984668955249590885041772800% [calculation:growth].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, LargeNumberFinancialTools())).run(
        "Compare Microsoft revenue growth.",
        session_id="session-human-number-formatting",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "82886000000.000000" not in result["final_answer"]
    assert "1.984668955249590885041772800" not in result["final_answer"]
    assert "82.89 billion USD" in result["final_answer"]
    assert "1.98%" in result["final_answer"]
    answer_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.ANSWER
    )
    assert "82886000000.000000" not in answer_context
    assert "1.984668955249590885041772800" not in answer_context
    assert "82.89 billion USD" in answer_context
    assert "1.98%" in answer_context
    assert all("82886000000.000000" not in item.label for item in result["citations"])


def test_answer_timeout_fallback_groups_peer_facts_by_period() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare Cloudflare and Netflix revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    cloudflare_facts = FinancialFactsBranch(
        branch_id="cloudflare_revenue",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            period_types=("annual",),
            limit=20,
        ),
    )
    netflix_facts = FinancialFactsBranch(
        branch_id="netflix_revenue",
        request=FinancialFactQuery(
            company_ids=(NETFLIX_ID,),
            metrics=("revenue",),
            period_types=("annual",),
            limit=20,
        ),
    )
    cloudflare_growth = CalculationBranch(
        branch_id="cloudflare_growth",
        operation="year_over_year_growth",
        input_refs=(cloudflare_facts.branch_id,),
        depends_on=(cloudflare_facts.branch_id,),
    )
    netflix_growth = CalculationBranch(
        branch_id="netflix_growth",
        operation="year_over_year_growth",
        input_refs=(netflix_facts.branch_id,),
        depends_on=(netflix_facts.branch_id,),
    )
    model = AnswerTimeoutModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(cloudflare_facts, netflix_facts, cloudflare_growth, netflix_growth),
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, PeerAnnualFinancialTools())).run(
        "Compare Cloudflare and Netflix revenue growth.",
        session_id="session-peer-fallback-table",
        policy=ExecutionPolicy(max_retries_per_node=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "| Period | Metric | Cloudflare | Netflix |" in result["final_answer"]
    assert "| 2025-12-31 | revenue | 125 USD " in result["final_answer"]
    assert " | 165 USD " in result["final_answer"]
    assert "| 2025-12-31 | Cloudflare | revenue |" not in result["final_answer"]
    assert result["answer_validation"].valid is True


def test_validation_failure_falls_back_to_deterministic_cited_summary() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(_financial_branch(),),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(f"Cloudflare revenue was 124.6 USD [financial_fact:{FACT_ID}].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was Cloudflare revenue?",
        session_id="session-validation-fallback",
        policy=ExecutionPolicy(max_repair_attempts=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert "\n\n| Period | Company | Metric | Value |" in result["final_answer"]
    assert "125 USD" in result["final_answer"]
    assert "124.6" not in result["final_answer"]
    assert "[financial_fact:" in result["final_answer"]


def test_validation_fallback_avoids_sentence_split_in_punctuated_company_name() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(_financial_branch(),),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(f"Elastic N.V. revenue was 124.6 USD [financial_fact:{FACT_ID}].",),
    )

    result = ResearchAgent(
        runtime=ResearchAgentRuntime(model, PunctuatedCompanyFinancialTools())
    ).run(
        "What was Elastic revenue?",
        session_id="session-punctuated-company-validation-fallback",
        policy=ExecutionPolicy(max_repair_attempts=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert "| 2025-12-31 | Elastic NV | revenue | 125 USD" in result["final_answer"]
