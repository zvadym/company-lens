from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_follow_up_without_company_mention_still_inherits_previous_company() -> None:
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
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    current = ResolvedQuery(query="do the same", fiscal_years=(2025,))

    merged = _merge_follow_up_resolution(current, previous)

    assert merged.company_ids == (COMPANY_ID,)
    assert [entity.kind for entity in merged.entities] == ["company"]
    assert merged.metrics == ("revenue",)
    assert merged.fiscal_years == (2025,)


def test_plural_company_follow_up_inherits_recent_company_set() -> None:
    cloudflare = ResolvedQuery(
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
    google = ResolvedQuery(
        query="зроби те саме для google",
        entities=(
            EntityResolution(
                kind="company",
                mention="google",
                status="resolved",
                canonical_value=str(NETFLIX_ID),
                candidates=(
                    EntityCandidate(
                        id=NETFLIX_ID,
                        canonical_value=str(NETFLIX_ID),
                        display_value="Alphabet Inc.",
                        match_kind="sec_company_name",
                    ),
                ),
            ),
        ),
        company_ids=(NETFLIX_ID,),
        metrics=("revenue",),
    )
    current = ResolvedQuery(query="тепер порівняй ці компанії на графіку")
    analysis = QuestionAnalysis(
        normalized_question=(
            "compare Cloudflare and Alphabet on a chart using their revenue growth "
            "over the last eight quarters"
        ),
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("comparison_requested", "chart_explicitly_requested"),
    )
    memory = SessionMemory(
        last_resolved_query=google,
        recent_resolved_queries=(cloudflare, google),
    )

    merged = _merge_follow_up_if_needed(current, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, NETFLIX_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "cloudflare",
        "google",
    ]
    assert merged.metrics == ("revenue",)


def test_add_series_follow_up_merges_new_company_with_previous_chart_companies() -> None:
    cloudflare = ResolvedQuery(
        query="Plot Cloudflare revenue growth against the federal funds rate.",
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
    tesla = ResolvedQuery(
        query="а тепер на графік виведи обидва",
        entities=(
            EntityResolution(
                kind="company",
                mention="tesla",
                status="resolved",
                canonical_value=str(NETFLIX_ID),
                candidates=(
                    EntityCandidate(
                        id=NETFLIX_ID,
                        canonical_value=str(NETFLIX_ID),
                        display_value="Tesla, Inc.",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(NETFLIX_ID, COMPANY_ID),
        metrics=("revenue",),
    )
    apple = ResolvedQuery(
        query="а тепер додай туди ще і Apple",
        entities=(
            EntityResolution(
                kind="company",
                mention="apple",
                status="resolved",
                canonical_value=str(APPLE_ID),
                candidates=(
                    EntityCandidate(
                        id=APPLE_ID,
                        canonical_value=str(APPLE_ID),
                        display_value="Apple Inc.",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(APPLE_ID,),
        metrics=("revenue",),
    )
    analysis = QuestionAnalysis(
        normalized_question="add Apple to the existing comparison chart",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "add_series", "comparison_chart"),
    )
    memory = SessionMemory(
        last_resolved_query=tesla,
        recent_resolved_queries=(cloudflare, tesla),
    )

    merged = _merge_follow_up_if_needed(apple, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, NETFLIX_ID, APPLE_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "apple",
        "cloudflare",
        "tesla",
    ]
    assert merged.metrics == ("revenue",)
