from __future__ import annotations

from company_lens.agent.schemas import NodeAttempt

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
            "company_not_identifiable",
            "no_available_company_data",
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


def test_exhausted_company_extraction_failure_is_preserved_in_agent_state() -> None:
    class FailingExtractionModel(FakeModelProvider):
        def generate_structured[OutputT: BaseModel](
            self,
            messages: Sequence[ModelMessage],
            output_type: type[OutputT],
            *,
            purpose: ModelPurpose,
        ) -> StructuredModelResult[OutputT]:
            if purpose is ModelPurpose.ENTITY_EXTRACTION:
                raise ModelProviderError(
                    AgentError(
                        category=AgentErrorCategory.PROVIDER_SERVICE,
                        severity=AgentErrorSeverity.RECOVERABLE,
                        code="openai_service",
                        message="OpenAI service returned a transient error.",
                    )
                )
            return super().generate_structured(messages, output_type, purpose=purpose)

    analysis = QuestionAnalysis(
        normalized_question="Compare Cloudflare and Datadog revenue growth.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    model = FailingExtractionModel(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
    )
    state = create_initial_agent_state(
        "Compare Cloudflare and Datadog revenue growth.",
        session_id="session-extraction-provider-failure",
        policy=ExecutionPolicy(max_retries_per_node=2),
    )
    state["analysis"] = analysis

    update = _resolve_entities(
        state,
        Runtime(context=ResearchAgentRuntime(model, FakeResearchTools())),
    )

    errors = cast(tuple[AgentError, ...], update["errors"])
    attempts = cast(tuple[NodeAttempt, ...], update["node_attempts"])
    assert [(error.category, error.code) for error in errors] == [
        (AgentErrorCategory.PROVIDER_SERVICE, "openai_service")
    ]
    assert attempts[0].attempts == 3
