from __future__ import annotations

import uuid

from company_lens.agent.schemas import (
    AgentRunStatus,
    AgentState,
    AnswerCompanyTarget,
    EvidenceEnvelope,
)


def answer_company_targets_from_state(state: AgentState) -> tuple[AnswerCompanyTarget, ...]:
    used_company_ids = _used_company_ids(state)
    if not used_company_ids and state["status"] in {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.PARTIAL,
    }:
        resolved = state.get("resolved_query")
        used_company_ids = resolved.company_ids if resolved is not None else ()
    if not used_company_ids:
        return ()

    details = _answer_company_details(state)
    targets: list[AnswerCompanyTarget] = []
    seen: set[uuid.UUID] = set()
    for company_id in used_company_ids:
        if company_id in seen:
            continue
        seen.add(company_id)
        detail = details.get(company_id, {})
        targets.append(
            AnswerCompanyTarget(
                company_id=company_id,
                ticker=_string_or_none(detail.get("ticker")),
                display_name=_string_or_none(detail.get("display_name")),
                mention=_string_or_none(detail.get("mention")),
            )
        )
    return tuple(targets)


def answer_company_targets_from_evidence(
    evidence: tuple[EvidenceEnvelope, ...],
) -> tuple[AnswerCompanyTarget, ...]:
    targets: list[AnswerCompanyTarget] = []
    seen: set[uuid.UUID] = set()
    for item in evidence:
        company_id = item.metadata.company_id
        if company_id is None or company_id in seen:
            continue
        seen.add(company_id)
        targets.append(
            AnswerCompanyTarget(
                company_id=company_id,
                display_name=item.metadata.company_name,
            )
        )
    return tuple(targets)


def _used_company_ids(state: AgentState) -> tuple[uuid.UUID, ...]:
    resolved = state.get("resolved_query")
    resolved_order = resolved.company_ids if resolved is not None else ()
    observed_ids: list[uuid.UUID] = []
    observed_seen: set[uuid.UUID] = set()
    for item in state.get("evidence", ()):
        company_id = item.metadata.company_id
        if company_id is not None and company_id not in observed_seen:
            observed_seen.add(company_id)
            observed_ids.append(company_id)
    for result in state.get("financial_results", ()):
        for observation in result.result.observations:
            if observation.company_id not in observed_seen:
                observed_seen.add(observation.company_id)
                observed_ids.append(observation.company_id)
    ordered: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for company_id in resolved_order:
        if company_id in observed_ids and company_id not in seen:
            seen.add(company_id)
            ordered.append(company_id)
    for company_id in observed_ids:
        if company_id not in seen:
            seen.add(company_id)
            ordered.append(company_id)
    return tuple(ordered)


def _answer_company_details(state: AgentState) -> dict[uuid.UUID, dict[str, str]]:
    details: dict[uuid.UUID, dict[str, str]] = {}
    frame = state.get("research_frame")
    if frame is not None:
        for target in frame.company_targets:
            if target.company_id is None or target.status != "resolved":
                continue
            entry = details.setdefault(target.company_id, {})
            if target.ticker:
                entry.setdefault("ticker", target.ticker)
            if target.display_name:
                entry.setdefault("display_name", target.display_name)
            if target.mention:
                entry.setdefault("mention", target.mention)
    for item in state.get("evidence", ()):
        company_id = item.metadata.company_id
        if company_id is None:
            continue
        entry = details.setdefault(company_id, {})
        if item.metadata.company_name:
            entry.setdefault("display_name", item.metadata.company_name)
    for result in state.get("financial_results", ()):
        for observation in result.result.observations:
            entry = details.setdefault(observation.company_id, {})
            if observation.ticker:
                entry["ticker"] = observation.ticker
            entry["display_name"] = observation.company_name
    return details


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
