from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_resolve_entities_extracts_follow_up_public_company_target() -> None:
    class CompanylessTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
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
                    display_name="Zoom Communications Inc.",
                    match_kind="sec_company_extracted",
                ),
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
    tools = CompanylessTools()
    state = create_initial_agent_state(
        "а тепер те саме для Zoom",
        session_id="session-follow-up-zoom",
    )
    state["analysis"] = analysis
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

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    frame = cast(ResearchFrame, update["research_frame"])
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Zoom"
    assert public_company.candidates[0].canonical_value == "ZM"
    assert frame.company_targets[0].mention == "Zoom"
    assert frame.company_targets[0].ticker == "ZM"
    assert frame.follow_up_operation == "quarter_over_quarter_growth"
    assert frame.follow_up_window == 8
    assert tools.calls["resolve_public_company_mentions"] == 1
    assert ModelPurpose.ENTITY_EXTRACTION in model.purposes


def test_resolve_entities_does_not_inherit_previous_company_for_unknown_extracted_target() -> None:
    class CompanylessTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Globex",
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
            companies=(CompanyMentionCandidate(mention="Globex"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = CompanylessTools()
    state = create_initial_agent_state(
        "а тепер те саме для Globex",
        session_id="session-follow-up-unknown-company",
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
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Globex"
    assert public_company.candidates == ()
    assert tools.calls["resolve_public_company_mentions"] == 1


def test_resolve_entities_does_not_inherit_previous_company_for_ambiguous_target() -> None:
    class AmbiguousCompanyTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Acme",)
            return (
                EntityResolution(
                    kind="public_company",
                    mention="Acme",
                    status="ambiguous",
                    candidates=(
                        EntityCandidate(
                            canonical_value="ACMA",
                            display_value="Acme Holdings Inc.",
                            match_kind="sec_company_extracted",
                        ),
                        EntityCandidate(
                            canonical_value="ACMB",
                            display_value="Acme Software Inc.",
                            match_kind="sec_company_extracted",
                        ),
                    ),
                ),
            )

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Acme",
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
            companies=(CompanyMentionCandidate(mention="Acme"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = AmbiguousCompanyTools()
    state = create_initial_agent_state(
        "а тепер те саме для Acme",
        session_id="session-follow-up-ambiguous-company",
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
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Acme"
    assert public_company.status == "ambiguous"
    assert [candidate.canonical_value for candidate in public_company.candidates] == [
        "ACMA",
        "ACMB",
    ]
    assert tools.calls["resolve_public_company_mentions"] == 1
