from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _prepare_company_data(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("prepare_company_data")
    resolved = state.get("resolved_query")
    if resolved is None:
        return _skipped("prepare_company_data")
    tickers = _on_demand_tickers(resolved)
    company_ids = tuple(str(company_id) for company_id in resolved.company_ids)
    if not tickers and not company_ids:
        return _skipped("prepare_company_data")

    started = time.monotonic()
    try:
        result = runtime.context.tools.prepare_companies(
            tickers=tickers,
            company_ids=company_ids,
            index_name=runtime.context.retrieval_index_name,
            index_version=runtime.context.retrieval_index_version,
        )
    except ResearchToolError as exc:
        error = exc.error.model_copy(update={"node": "prepare_company_data"})
        return {
            "errors": (error,),
            "node_attempts": (NodeAttempt(node="prepare_company_data", attempts=1),),
            "trajectory": (
                _event(
                    "prepare_company_data",
                    TrajectoryStatus.COMPLETED,
                    "Company report download was unavailable; continuing with existing data.",
                    started,
                ),
            ),
        }
    resolved_tickers = tuple(dict.fromkeys((*result.prepared_tickers, *result.skipped_tickers)))
    if resolved_tickers:
        with suppress(Exception):
            resolved = _resolve_question_entities(
                state["question"],
                state.get("analysis"),
                runtime.context.tools,
            )
            resolved = _resolve_extracted_company_mentions(
                state,
                runtime,
                resolved,
                state.get("analysis"),
            )
            if not resolved.company_ids:
                resolved = _merge_prepared_ticker_resolutions(
                    resolved,
                    _resolve_prepared_tickers(runtime.context.tools, resolved_tickers),
                )
            resolved = _merge_follow_up_if_needed(
                resolved,
                state.get("analysis"),
                state.get("session_memory"),
            )
    frame = _build_research_frame(
        question=state["question"],
        analysis=state.get("analysis"),
        resolved=resolved,
        memory=state.get("session_memory"),
    )

    summary = (
        "Company report data is already available."
        if result.status == "skipped"
        else "Company report data was downloaded and indexed."
        if result.status == "success"
        else "Company report data was partially prepared."
    )
    return {
        "resolved_query": resolved,
        "research_frame": frame,
        "node_attempts": (NodeAttempt(node="prepare_company_data", attempts=1),),
        "trajectory": (
            _event(
                "prepare_company_data",
                TrajectoryStatus.COMPLETED,
                summary,
                started,
                details={
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
    merged_company_entities = tuple(company_entities) or original_company_entities
    return resolved.model_copy(
        update={
            "entities": (*merged_company_entities, *non_company_entities),
            "company_ids": tuple(company_ids),
        }
    )


__all__ = (
    "_prepare_company_data",
    "_resolve_prepared_tickers",
    "_merge_prepared_ticker_resolutions",
)  # noqa: E501
