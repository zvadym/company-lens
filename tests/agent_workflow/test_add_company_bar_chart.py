from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_add_company_bar_chart_follow_up_prepares_ticker_without_unresolved_duplicate() -> None:
    class AddAmazonTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if query == "AMZN":
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="company",
                            mention="amzn",
                            status="resolved",
                            canonical_value=str(AMAZON_ID),
                            candidates=(
                                EntityCandidate(
                                    id=AMAZON_ID,
                                    canonical_value=str(AMAZON_ID),
                                    display_value="AMAZON COM INC",
                                    match_kind="ticker",
                                ),
                            ),
                        ),
                        public_company_resolution(
                            mention="amzn",
                            ticker="AMZN",
                            display_name="AMAZON COM INC",
                            match_kind="sec_company_ticker",
                        ),
                    ),
                    company_ids=(AMAZON_ID,),
                    metrics=("revenue",),
                )
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve_non_company"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("amazon",)
            return (
                public_company_resolution(
                    mention="amazon",
                    ticker="AMZN",
                    display_name="AMAZON COM INC",
                    match_kind="sec_company_extracted",
                ),
            )

        def prepare_companies(
            self,
            *,
            tickers: tuple[str, ...],
            company_ids: tuple[str, ...],
            index_name: str,
            index_version: str,
        ) -> CompanyDataPreparationResult:
            self.calls["prepare"] += 1
            assert tickers == ("AMZN",)
            assert company_ids == (str(MICROSOFT_ID),)
            return CompanyDataPreparationResult(
                status="success",
                requested_tickers=tickers,
                skipped_tickers=(),
                prepared_tickers=tickers,
                companies_seen=1,
                filings_seen=2,
                facts_seen=8,
                documents_processed=2,
                chunks_indexed=4,
            )

        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            assert request.metrics == ("revenue",)
            company_id = request.company_ids[0]
            company_name = "AMAZON COM INC" if company_id == AMAZON_ID else "MICROSOFT CORP"
            ticker = "AMZN" if company_id == AMAZON_ID else "MSFT"
            return FinancialFactQueryResult(
                query=request,
                observations=(
                    _financial_observation(date(2025, 9, 30), Decimal("100")).model_copy(
                        update={
                            "id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_id}-2025-q3"),
                            "company_id": company_id,
                            "company_name": company_name,
                            "ticker": ticker,
                            "period_type": "quarter",
                            "fiscal_period": "Q3",
                        }
                    ),
                    _financial_observation(date(2026, 3, 31), Decimal("125")).model_copy(
                        update={
                            "id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_id}-2026-q1"),
                            "company_id": company_id,
                            "company_name": company_name,
                            "ticker": ticker,
                            "period_type": "quarter",
                            "fiscal_period": "Q1",
                        }
                    ),
                ),
                available_units=("USD",),
            )

    analysis = QuestionAnalysis(
        normalized_question=(
            "Compare Microsoft and Amazon revenue growth over the last eight quarters "
            "and build a bar chart."
        ),
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=(
            "follow_up_request",
            "adds_company",
            "explicit_chart_request",
            "requires_growth_calculation",
        ),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="microsoft_revenue",
                request=FinancialFactQuery(
                    company_ids=(MICROSOFT_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="microsoft_growth",
                operation="quarter_over_quarter_growth",
                input_refs=("microsoft_revenue",),
                depends_on=("microsoft_revenue",),
            ),
            FinancialFactsBranch(
                branch_id="amazon_revenue",
                request=FinancialFactQuery(
                    company_ids=(AMAZON_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="amazon_growth",
                operation="quarter_over_quarter_growth",
                input_refs=("amazon_revenue",),
                depends_on=("amazon_revenue",),
            ),
            ChartBranch(
                branch_id="growth_chart",
                chart_type="bar",
                dataset_ref="microsoft_growth",
                depends_on=("microsoft_growth", "amazon_growth"),
                title="Microsoft and Amazon revenue growth",
            ),
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="amazon"),),
            reason_codes=("explicit_added_company",),
        ),
    )
    tools = AddAmazonTools()
    microsoft = ResolvedQuery(
        query="а тепер зроби те саме для microsoft",
        entities=(
            EntityResolution(
                kind="company",
                mention="msft",
                status="resolved",
                canonical_value=str(MICROSOFT_ID),
                candidates=(
                    EntityCandidate(
                        id=MICROSOFT_ID,
                        canonical_value=str(MICROSOFT_ID),
                        display_value="MICROSOFT CORP",
                        match_kind="ticker",
                    ),
                ),
            ),
        ),
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    state = create_initial_agent_state(
        "а тепер додай amazon і побудуй bar chart",
        session_id="session-add-amazon-bar-chart",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=microsoft,
        recent_resolved_queries=(microsoft,),
    )

    resolve_update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))
    state.update(resolve_update)
    prepare_update = _prepare_company_data(
        state,
        Runtime(context=ResearchAgentRuntime(model, tools)),
    )
    state.update(prepare_update)

    resolved = cast(ResolvedQuery, state["resolved_query"])
    frame = cast(ResearchFrame, state["research_frame"])
    assert resolved.company_ids == (MICROSOFT_ID, AMAZON_ID)
    assert not any(
        entity.kind == "public_company"
        and entity.candidates
        and entity.candidates[0].canonical_value == "AMZN"
        for entity in resolved.entities
    )
    assert [target.company_id for target in frame.company_targets] == [
        AMAZON_ID,
        MICROSOFT_ID,
    ]
    assert all(target.status == "resolved" for target in frame.company_targets)

    plan_update = _plan_request(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    assert "errors" not in plan_update
    execution_plan = cast(ExecutionPlan, plan_update["execution_plan"])
    assert execution_plan.branches[-1].kind == "generate_chart_spec"
    assert tools.calls["prepare"] == 1
    assert tools.calls["resolve_public_company_mentions"] == 2
