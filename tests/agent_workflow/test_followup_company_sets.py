from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def _company_query(
    query: str,
    *,
    company_id: uuid.UUID,
    mention: str,
    display_value: str,
    metrics: tuple[str, ...] = ("revenue",),
) -> ResolvedQuery:
    return ResolvedQuery(
        query=query,
        entities=(
            _company_entity(
                company_id=company_id,
                mention=mention,
                display_value=display_value,
            ),
        ),
        company_ids=(company_id,),
        metrics=metrics,
    )


def _company_entity(
    *,
    company_id: uuid.UUID,
    mention: str,
    display_value: str,
    match_kind: str = "display_name",
) -> EntityResolution:
    return EntityResolution(
        kind="company",
        mention=mention,
        status="resolved",
        canonical_value=str(company_id),
        candidates=(
            EntityCandidate(
                id=company_id,
                canonical_value=str(company_id),
                display_value=display_value,
                match_kind=match_kind,
            ),
        ),
    )


def test_follow_up_without_company_mention_still_inherits_previous_company() -> None:
    previous = _company_query(
        query="Compare Cloudflare revenue growth",
        company_id=COMPANY_ID,
        mention="cloudflare",
        display_value="Cloudflare",
    )
    current = ResolvedQuery(query="do the same", fiscal_years=(2025,))

    merged = _merge_follow_up_resolution(current, previous)

    assert merged.company_ids == (COMPANY_ID,)
    assert [entity.kind for entity in merged.entities] == ["company"]
    assert merged.metrics == ("revenue",)
    assert merged.fiscal_years == (2025,)


def test_plural_company_follow_up_inherits_recent_company_set() -> None:
    cloudflare = _company_query(
        query="Compare Cloudflare revenue growth",
        company_id=COMPANY_ID,
        mention="cloudflare",
        display_value="Cloudflare",
    )
    google = _company_query(
        query="зроби те саме для google",
        company_id=NETFLIX_ID,
        mention="google",
        display_value="Alphabet Inc.",
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


def test_compare_them_follow_up_inherits_recent_company_set_without_chart() -> None:
    cloudflare = _company_query(
        query="Compare Cloudflare revenue growth over the last eight quarters.",
        company_id=COMPANY_ID,
        mention="Cloudflare",
        display_value="Cloudflare",
    )
    netflix = _company_query(
        query="do the same for Netflix",
        company_id=NETFLIX_ID,
        mention="Netflix",
        display_value="Netflix, Inc.",
    )
    current = ResolvedQuery(query="and now compare them")
    analysis = QuestionAnalysis(
        normalized_question=(
            "compare Cloudflare and Netflix revenue growth over the last eight quarters"
        ),
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
        reason_codes=("comparison_requested",),
    )
    memory = SessionMemory(
        last_resolved_query=netflix,
        recent_resolved_queries=(cloudflare, netflix),
    )

    merged = _merge_follow_up_if_needed(current, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, NETFLIX_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "Cloudflare",
        "Netflix",
    ]
    assert merged.metrics == ("revenue",)


def test_add_series_follow_up_merges_new_company_with_previous_chart_companies() -> None:
    cloudflare = _company_query(
        query="Plot Cloudflare revenue growth against the federal funds rate.",
        company_id=COMPANY_ID,
        mention="cloudflare",
        display_value="Cloudflare",
    )
    tesla = ResolvedQuery(
        query="а тепер на графік виведи обидва",
        entities=(
            _company_entity(
                company_id=NETFLIX_ID,
                mention="tesla",
                display_value="Tesla, Inc.",
                match_kind="normalized_legal_name",
            ),
        ),
        company_ids=(NETFLIX_ID, COMPANY_ID),
        metrics=("revenue",),
    )
    apple = _company_query(
        query="а тепер додай туди ще і Apple",
        company_id=APPLE_ID,
        mention="apple",
        display_value="Apple Inc.",
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
