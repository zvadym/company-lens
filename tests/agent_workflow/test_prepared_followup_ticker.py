from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_prepared_follow_up_company_resolves_company_id_from_extracted_ticker() -> None:
    class PreparedZoomTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if query == "ZM":
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="company",
                            mention="zm",
                            status="resolved",
                            canonical_value=str(ZOOM_ID),
                            candidates=(
                                EntityCandidate(
                                    id=ZOOM_ID,
                                    canonical_value=str(ZOOM_ID),
                                    display_value="Zoom Communications, Inc.",
                                    match_kind="ticker",
                                ),
                            ),
                        ),
                    ),
                    company_ids=(ZOOM_ID,),
                    metrics=("revenue",),
                )
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Zoom",)
            return (
                public_company_resolution(
                    mention="Zoom",
                    ticker="ZM",
                    display_name="Zoom Communications, Inc.",
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
            assert tickers == ("ZM",)
            assert company_ids == ()
            return CompanyDataPreparationResult(
                status="success",
                requested_tickers=tickers,
                skipped_tickers=(),
                prepared_tickers=tickers,
                companies_seen=1,
                filings_seen=1,
                facts_seen=8,
                documents_processed=1,
                chunks_indexed=2,
            )

        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            assert request.company_ids == (ZOOM_ID,)
            observations = (
                _financial_observation(date(2025, 9, 30), Decimal("120")).model_copy(
                    update={
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, "zoom-2025-q3"),
                        "company_id": ZOOM_ID,
                        "company_name": "Zoom Communications, Inc.",
                        "ticker": "ZM",
                        "period_start": date(2025, 7, 1),
                        "period_type": "quarter",
                        "fiscal_period": "Q3",
                    }
                ),
                _financial_observation(date(2025, 12, 31), Decimal("132")).model_copy(
                    update={
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, "zoom-2025-q4"),
                        "company_id": ZOOM_ID,
                        "company_name": "Zoom Communications, Inc.",
                        "ticker": "ZM",
                        "period_start": date(2025, 10, 1),
                        "period_type": "quarter",
                        "fiscal_period": "Q4",
                    }
                ),
            )
            return FinancialFactQueryResult(
                query=request,
                observations=observations,
                available_units=("USD",),
            )

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Zoom",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
        reason_codes=("follow_up", "revenue_growth_requested"),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                FinancialFactsBranch(
                    branch_id="source_revenue_quarters",
                    request=FinancialFactQuery(metrics=("revenue",), limit=8),
                ),
                CalculationBranch(
                    branch_id="revenue_qoq_growth",
                    operation="quarter_over_quarter_growth",
                    input_refs=("source_revenue_quarters",),
                    window=8,
                ),
            ),
        ),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Zoom"),),
            reason_codes=("explicit_company_target",),
        ),
        texts=("Zoom revenue grew 10% quarter over quarter [calculation:revenue_qoq_growth].",),
    )
    tools = PreparedZoomTools()
    state = create_initial_agent_state(
        "а тепер те саме для Zoom",
        session_id="session-follow-up-prepared-zoom",
    )
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    result = build_research_graph().invoke(
        state,
        config={"recursion_limit": 24},
        context=ResearchAgentRuntime(model, tools),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["resolved_query"].company_ids == (ZOOM_ID,)
    assert tools.calls["prepare"] == 1
    assert tools.calls["financial"] == 2
