from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _prepare_company_data(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("prepare_company_data")
    current = state.get("current_resolved_query") or state.get("resolved_query")
    if current is None:
        return _skipped("prepare_company_data")
    requirements = _company_data_preparation_requirements(state.get("analysis"))
    record_company_preparation_requirements(
        financial_facts=requirements.financial_facts,
        documents=requirements.documents,
    )
    tickers = _on_demand_tickers(current)
    company_ids = tuple(str(company_id) for company_id in current.company_ids)
    details = {
        "requires_financial_facts": requirements.financial_facts,
        "requires_documents": requirements.documents,
    }
    if not requirements.any or (not tickers and not company_ids):
        finalized = _finalize_prepared_company_context(state, runtime, current)
        return {
            **finalized,
            "trajectory": (
                _event(
                    "prepare_company_data",
                    TrajectoryStatus.SKIPPED,
                    "No external company data preparation was required.",
                    time.monotonic(),
                    details=details,
                ),
            ),
        }

    started = time.monotonic()
    try:
        result = runtime.context.tools.prepare_companies(
            tickers=tickers,
            company_ids=company_ids,
            index_name=runtime.context.retrieval_index_name,
            index_version=runtime.context.retrieval_index_version,
            requirements=requirements,
        )
    except ResearchToolError as exc:
        error = exc.error.model_copy(update={"node": "prepare_company_data"})
        finalized = _finalize_prepared_company_context(state, runtime, current)
        return {
            **finalized,
            "errors": (error,),
            "node_attempts": (NodeAttempt(node="prepare_company_data", attempts=1),),
            "trajectory": (
                _event(
                    "prepare_company_data",
                    TrajectoryStatus.COMPLETED,
                    "Company report download was unavailable; continuing with existing data.",
                    started,
                    details=details,
                ),
            ),
        }
    resolved_tickers = tuple(dict.fromkeys((*result.prepared_tickers, *result.skipped_tickers)))
    finalized = _finalize_prepared_company_context(
        state,
        runtime,
        current,
        resolved_tickers=resolved_tickers,
    )

    summary = (
        "Company report data is already available."
        if result.status == "skipped"
        else "Required company data was prepared."
        if result.status == "success"
        else "Company report data was partially prepared."
    )
    return {
        **finalized,
        "node_attempts": (NodeAttempt(node="prepare_company_data", attempts=1),),
        "trajectory": (
            _event(
                "prepare_company_data",
                TrajectoryStatus.COMPLETED,
                summary,
                started,
                details={
                    **details,
                    "requested_tickers": ",".join(result.requested_tickers),
                    "prepared_tickers": ",".join(result.prepared_tickers),
                    "skipped_tickers": ",".join(result.skipped_tickers),
                    "companies_seen": result.companies_seen,
                    "filings_seen": result.filings_seen,
                    "facts_seen": result.facts_seen,
                    "documents_processed": result.documents_processed,
                    "chunks_indexed": result.chunks_indexed,
                    "failures": result.failures,
                },
            ),
        ),
    }


def _company_data_preparation_requirements(
    analysis: QuestionAnalysis | None,
) -> CompanyDataPreparationRequirements:
    capabilities = set(analysis.required_capabilities) if analysis is not None else set()
    return CompanyDataPreparationRequirements(
        financial_facts=AgentCapability.FINANCIAL_FACTS in capabilities,
        documents=AgentCapability.DOCUMENTS in capabilities,
    )


def _finalize_prepared_company_context(
    state: AgentState,
    runtime: Runtime[ResearchAgentRuntime],
    current: ResolvedQuery,
    *,
    resolved_tickers: tuple[str, ...] = (),
) -> dict[str, object]:
    enriched_current = current
    if resolved_tickers:
        with suppress(Exception):
            enriched_current = _merge_prepared_ticker_resolutions(
                current,
                _resolve_prepared_tickers(runtime.context.tools, resolved_tickers),
            )
    merged = _merge_follow_up_if_needed(
        enriched_current,
        state.get("analysis"),
        state.get("session_memory"),
    )
    frame = _build_research_frame(
        question=state["question"],
        analysis=state.get("analysis"),
        resolved=merged,
        current_resolved=enriched_current,
        memory=state.get("session_memory"),
    )
    return {
        "current_resolved_query": enriched_current,
        "resolved_query": merged,
        "research_frame": frame,
    }


def _resolve_prepared_tickers(
    tools: ResearchTools,
    tickers: tuple[str, ...],
) -> tuple[ResolvedQuery, ...]:
    return tuple(tools.resolve_entities(ticker) for ticker in tickers)


def _merge_prepared_ticker_resolutions(
    resolved: ResolvedQuery,
    ticker_resolutions: tuple[ResolvedQuery, ...],
) -> ResolvedQuery:
    company_ids: list[uuid.UUID] = list(resolved.company_ids)
    company_entities: list[EntityResolution] = []
    locally_resolved_tickers: set[str] = set()
    seen_company_ids = set(company_ids)
    seen_entities = {
        (entity.kind, entity.canonical_value or entity.mention.casefold())
        for entity in resolved.entities
        if entity.kind in {"company", "public_company"}
    }
    for ticker_resolution in ticker_resolutions:
        ticker_has_resolved_company = bool(ticker_resolution.company_ids) or any(
            entity.kind == "company" and _entity_company_id(entity) is not None
            for entity in ticker_resolution.entities
        )
        if ticker_has_resolved_company:
            locally_resolved_tickers.add(ticker_resolution.query.strip().upper())
        for company_id in ticker_resolution.company_ids:
            if company_id not in seen_company_ids:
                seen_company_ids.add(company_id)
                company_ids.append(company_id)
        for entity in ticker_resolution.entities:
            if entity.kind not in {"company", "public_company"}:
                continue
            # Once the downloaded ticker resolves to a local company row, keeping the
            # public-company placeholder would create a second unresolved target for
            # the same SEC ticker and make the planner reject otherwise valid plans.
            if entity.kind == "public_company" and ticker_has_resolved_company:
                continue
            key = (entity.kind, entity.canonical_value or entity.mention.casefold())
            if key in seen_entities:
                continue
            seen_entities.add(key)
            company_entities.append(entity)
    if not company_ids and not company_entities:
        return resolved
    original_company_entities = tuple(
        entity for entity in resolved.entities if entity.kind in {"company", "public_company"}
    )
    non_company_entities = tuple(
        entity for entity in resolved.entities if entity.kind not in {"company", "public_company"}
    )
    retained_original_entities = tuple(
        entity
        for entity in original_company_entities
        if not (
            entity.kind == "public_company"
            and _entity_public_ticker(entity) in locally_resolved_tickers
        )
    )
    merged_company_entities = (*retained_original_entities, *company_entities)
    return resolved.model_copy(
        update={
            "entities": (*merged_company_entities, *non_company_entities),
            "company_ids": tuple(company_ids),
        }
    )


__all__ = (
    "_prepare_company_data",
    "_company_data_preparation_requirements",
    "_finalize_prepared_company_context",
    "_resolve_prepared_tickers",
    "_merge_prepared_ticker_resolutions",
)  # noqa: E501
