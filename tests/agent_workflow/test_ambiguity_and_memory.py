from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_ambiguous_company_follow_up_asks_for_clarification_before_planning() -> None:
    class AmbiguousUnitedTools(FakeResearchTools):
        def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve_non_company"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("United",)
            return (
                EntityResolution(
                    kind="public_company",
                    mention="United",
                    status="ambiguous",
                    candidates=(
                        EntityCandidate(
                            canonical_value="UAL",
                            display_value="United Airlines Holdings Inc.",
                            match_kind="sec_company_extracted",
                        ),
                        EntityCandidate(
                            canonical_value="BNO",
                            display_value="United States Brent Oil Fund LP",
                            match_kind="sec_company_extracted",
                        ),
                    ),
                ),
            )

        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            raise AssertionError("ambiguous company should not reach financial facts")

    analysis = QuestionAnalysis(
        normalized_question="now do the same for United",
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
            companies=(
                CompanyMentionCandidate(
                    mention="United Acquisition Corp. I",
                    ticker="UAC",
                    legal_name="United Acquisition Corp. I",
                ),
            ),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = AmbiguousUnitedTools()
    state = create_initial_agent_state(
        "Now do the same for United",
        session_id="session-follow-up-united-clarification",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    resolve_update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))
    state.update(resolve_update)
    prepare_update = _prepare_company_data(
        state,
        Runtime(context=ResearchAgentRuntime(model, tools)),
    )
    state.update(prepare_update)
    plan_update = _plan_request(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, state["resolved_query"])
    answer = cast(str, plan_update["draft_answer"])
    assert plan_update["status"] is AgentRunStatus.ABSTAINED
    assert any(error.code == "ambiguous_company" for error in plan_update["errors"])
    assert resolved.company_ids == ()
    assert "Please clarify which company" in answer
    assert "United Airlines Holdings Inc. (UAL)" in answer
    assert "United States Brent Oil Fund LP (BNO)" in answer
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls["prepare"] == 0
    assert tools.calls["financial"] == 0


def test_chart_type_follow_up_does_not_treat_bar_as_company() -> None:
    class BarTickerTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(
                query=query,
                entities=(
                    public_company_resolution(
                        mention="bar",
                        ticker="BAR",
                        display_name="GraniteShares Gold Trust",
                        match_kind="sec_company_ticker",
                    ),
                ),
                metrics=("revenue",),
            )

    analysis = QuestionAnalysis(
        normalized_question="build a bar chart from the same data",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=(
            "explicit_chart_request",
            "follow_up_on_prior_table",
            "derived_comparison",
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.HYBRID),
        company_extraction=CompanyMentionExtraction(
            companies=(),
            reason_codes=("no_company_mentioned", "bar_is_chart_type"),
        ),
    )
    tools = BarTickerTools()
    state = create_initial_agent_state(
        "а тепер побудуй bar chart на цих данних",
        session_id="session-follow-up-bar-chart",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    assert resolved.company_ids == (COMPANY_ID,)
    assert all(entity.mention != "bar" for entity in resolved.entities)
    assert all(
        not (entity.candidates and entity.candidates[0].display_value == "GraniteShares Gold Trust")
        for entity in resolved.entities
    )
    assert tools.calls["resolve_public_company_mentions"] == 0
    assert ModelPurpose.ENTITY_EXTRACTION in model.purposes


def test_failed_turn_does_not_promote_bad_company_resolution_to_session_memory() -> None:
    previous = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    bad_bar_resolution = ResolvedQuery(
        query="а тепер побудуй bar chart на цих данних",
        entities=(
            EntityResolution(
                kind="company",
                mention="bar",
                status="resolved",
                canonical_value=str(APPLE_ID),
                candidates=(
                    EntityCandidate(
                        id=APPLE_ID,
                        canonical_value=str(APPLE_ID),
                        display_value="GraniteShares Gold Trust",
                        match_kind="ticker",
                    ),
                ),
            ),
            public_company_resolution(
                mention="bar",
                ticker="BAR",
                display_name="GraniteShares Gold Trust",
                match_kind="sec_company_ticker",
            ),
        ),
        company_ids=(APPLE_ID,),
        metrics=("revenue",),
    )
    state = create_initial_agent_state(
        "а тепер побудуй bar chart на цих данних",
        session_id="session-failed-memory-promotion",
    )
    state["status"] = AgentRunStatus.FAILED
    state["resolved_query"] = bad_bar_resolution
    state["session_memory"] = SessionMemory(
        last_resolved_query=previous,
        recent_resolved_queries=(previous,),
    )

    memory = _updated_session_memory(
        state,
        cache_limit=20,
        promote_current_context=False,
    )

    assert memory.last_resolved_query == previous
    assert memory.recent_resolved_queries == (previous,)
    assert all(
        entity.mention != "bar"
        for query in memory.recent_resolved_queries
        for entity in query.entities
    )
