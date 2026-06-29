from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_workflow_prepares_unavailable_public_company_before_planning() -> None:
    class OnDemandTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if self.calls["resolve"] == 1:
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="public_company",
                            mention="netflix",
                            status="unresolved",
                            candidates=(
                                EntityCandidate(
                                    canonical_value="NFLX",
                                    display_value="NETFLIX INC",
                                    match_kind="sec_company_name",
                                ),
                            ),
                        ),
                    ),
                )
            return ResolvedQuery(query=query, company_ids=(COMPANY_ID,))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Netflix",)
            return (
                public_company_resolution(
                    mention="Netflix",
                    ticker="NFLX",
                    display_name="NETFLIX INC",
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
            assert tickers == ("NFLX",)
            assert company_ids == ()
            return CompanyDataPreparationResult(
                status="success",
                requested_tickers=tickers,
                skipped_tickers=(),
                prepared_tickers=tickers,
                companies_seen=1,
                filings_seen=1,
                facts_seen=10,
                documents_processed=1,
                chunks_indexed=2,
            )

    analysis = QuestionAnalysis(
        normalized_question="What risks did Netflix report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(query="Netflix business risks"),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Netflix"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = OnDemandTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What risks did Netflix report?", session_id="session-on-demand"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["prepare"] == 1
    assert tools.calls["resolve"] == 2


def test_follow_up_with_new_public_company_does_not_inherit_previous_company() -> None:
    previous = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
            EntityResolution(
                kind="financial_metric",
                mention="revenue",
                status="resolved",
                canonical_value="revenue",
                candidates=(
                    EntityCandidate(
                        canonical_value="revenue",
                        display_value="revenue",
                        match_kind="metric_alias",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    current = ResolvedQuery(
        query="а тепер те саме для google",
        entities=(
            EntityResolution(
                kind="public_company",
                mention="google",
                status="unresolved",
                candidates=(
                    EntityCandidate(
                        canonical_value="GOOG",
                        display_value="Alphabet Inc.",
                        match_kind="sec_company_name",
                    ),
                ),
            ),
        ),
    )

    merged = _merge_follow_up_resolution(current, previous)

    assert merged.company_ids == ()
    assert [entity.kind for entity in merged.entities] == [
        "public_company",
        "financial_metric",
    ]
    assert merged.entities[0].candidates[0].canonical_value == "GOOG"
    assert merged.metrics == ("revenue",)
