from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_unsupported_unknown_company_is_extracted_before_follow_up_merge() -> None:
    class CompanylessTools(FakeResearchTools):
        def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve_non_company"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

    analysis = QuestionAnalysis(
        normalized_question="Show Globex year-over-year revenue growth.",
        route=ResearchRoute.UNSUPPORTED,
        is_follow_up=True,
        reason_codes=(
            "company_not_identified",
            "no_usable_source",
            "unsupported_analysis_normalized",
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Globex"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = CompanylessTools()
    state = create_initial_agent_state(
        "Do the same for Globex.",
        session_id="session-follow-up-unsupported-company",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Show Netflix year-over-year revenue growth.",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Globex"
    assert public_company.status == "unresolved"
    assert tools.calls["resolve_public_company_mentions"] == 1
    assert ModelPurpose.ENTITY_EXTRACTION in model.purposes
