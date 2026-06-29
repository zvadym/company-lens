from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_ready_follow_up_ticker_resolves_company_id_from_skipped_prepare() -> None:
    class ReadyZoomTools(FakeResearchTools):
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
                status="skipped",
                requested_tickers=tickers,
                skipped_tickers=tickers,
                prepared_tickers=(),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Zoom revenue growth over the last eight quarters.",
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
            companies=(CompanyMentionCandidate(mention="Zoom"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = ReadyZoomTools()
    state = create_initial_agent_state(
        "а тепер те саме для Zoom",
        session_id="session-follow-up-ready-zoom",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="а тепер те саме для Zoom",
        entities=(
            public_company_resolution(
                mention="Zoom",
                ticker="ZM",
                display_name="Zoom Communications, Inc.",
                match_kind="sec_company_extracted",
            ),
        ),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _prepare_company_data(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    frame = cast(ResearchFrame, update["research_frame"])
    assert resolved.company_ids == (ZOOM_ID,)
    assert frame.company_targets[0].company_id == ZOOM_ID
    assert frame.company_targets[0].source == "current_question"
    assert not frame.inherited_from_previous
    assert tools.calls["prepare"] == 1
    assert tools.calls["resolve_public_company_mentions"] == 1


def test_plan_request_abstains_before_planning_when_follow_up_financial_data_missing() -> None:
    class MissingFinancialFactsTools(FakeResearchTools):
        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            assert request.company_ids == (NOKIA_ID,)
            assert request.metrics == ("revenue",)
            return FinancialFactQueryResult(
                query=request,
                observations=(),
                available_units=(),
                warnings=("no_matching_financial_facts",),
            )

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Nokia",
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
    )
    state = create_initial_agent_state(
        "а тепер те саме для Nokia",
        session_id="session-follow-up-nokia-missing-readiness",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="а тепер те саме для Nokia",
        entities=(
            EntityResolution(
                kind="company",
                mention="nokia",
                status="resolved",
                canonical_value=str(NOKIA_ID),
                candidates=(
                    EntityCandidate(
                        id=NOKIA_ID,
                        canonical_value=str(NOKIA_ID),
                        display_value="NOKIA CORP",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(NOKIA_ID,),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        ),
        last_execution_plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                CalculationBranch(
                    branch_id="revenue_qoq_growth",
                    operation="quarter_over_quarter_growth",
                    input_refs=("source_revenue_quarters",),
                    window=8,
                ),
            ),
        ),
    )
    tools = MissingFinancialFactsTools()

    update = _plan_request(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    frame = cast(ResearchFrame, update["research_frame"])
    assert update["status"] is AgentRunStatus.ABSTAINED
    assert update["draft_answer"] is not None
    assert "NOKIA CORP" in cast(str, update["draft_answer"])
    assert frame.financial_readiness[0].status == "missing"
    assert frame.financial_readiness[0].warnings == ("no_matching_financial_facts",)
    assert tools.calls["financial"] == 1
    assert ModelPurpose.PLAN not in model.purposes
