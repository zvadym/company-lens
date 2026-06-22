from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from company_lens.agent.persistence import ResearchSessionMetadata, ResearchSessionSnapshot
from company_lens.agent.schemas import (
    AgentError,
    AgentRunStatus,
    AgentState,
    BranchOutcome,
    EvidenceKind,
    ResearchRoute,
    TrajectoryEvent,
)
from company_lens.analytics.schemas import ChartSpecification
from company_lens.evidence.schemas import AnswerValidation, ClaimRecord, SourcePreview


class OutputModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ResearchCitationOutput(OutputModel):
    evidence_id: str
    label: str
    kind: EvidenceKind
    summary: str
    source_urls: tuple[str, ...]
    lineage_refs: tuple[str, ...]
    claim_ids: tuple[str, ...] = ()


class ResearchExecutionOutput(OutputModel):
    tool_calls_used: int
    repair_attempts: int
    branches: tuple[BranchOutcome, ...]
    errors: tuple[AgentError, ...]
    trajectory: tuple[TrajectoryEvent, ...] = ()


class ResearchRunOutput(OutputModel):
    session_id: str
    run_id: uuid.UUID
    status: AgentRunStatus
    route: ResearchRoute | None
    answer: str | None
    claims: tuple[ClaimRecord, ...]
    citations: tuple[ResearchCitationOutput, ...]
    validation: AnswerValidation | None
    sources: tuple[SourcePreview, ...]
    chart: ChartSpecification | None
    execution: ResearchExecutionOutput


class ResearchSessionOutput(OutputModel):
    metadata: ResearchSessionMetadata
    checkpoint_id: str | None
    pending_nodes: tuple[str, ...]
    resumable: bool
    latest_run: ResearchRunOutput | None


class ResearchOperationOutput(OutputModel):
    operation: Literal["setup", "clear", "expire"]
    status: Literal["completed"] = "completed"
    session_id: str | None = None
    deleted: bool | None = None
    expired: int | None = None


class ResearchErrorDetail(OutputModel):
    code: str
    message: str


class ResearchErrorOutput(OutputModel):
    error: ResearchErrorDetail


def research_run_output(
    state: AgentState,
    *,
    include_trajectory: bool = False,
) -> ResearchRunOutput:
    evidence = {item.evidence_id: item for item in state.get("evidence", ())}
    citations = tuple(
        ResearchCitationOutput(
            evidence_id=citation.evidence_id,
            label=citation.label,
            kind=evidence[citation.evidence_id].kind,
            summary=evidence[citation.evidence_id].summary,
            source_urls=evidence[citation.evidence_id].source_urls,
            lineage_refs=evidence[citation.evidence_id].lineage_refs,
            claim_ids=citation.claim_ids,
        )
        for citation in state.get("citations", ())
        if citation.evidence_id in evidence
    )
    analysis = state.get("analysis")
    return ResearchRunOutput(
        session_id=state["session_id"],
        run_id=state["run_id"],
        status=state["status"],
        route=analysis.route if analysis is not None else None,
        answer=state.get("final_answer"),
        claims=state.get("claims", ()),
        citations=citations,
        validation=state.get("answer_validation"),
        sources=state.get("source_previews", ()),
        chart=state.get("chart_spec"),
        execution=ResearchExecutionOutput(
            tool_calls_used=state.get("tool_calls_used", 0),
            repair_attempts=state.get("repair_attempts", 0),
            branches=state.get("branch_outcomes", ()),
            errors=state.get("errors", ()),
            trajectory=state.get("trajectory", ()) if include_trajectory else (),
        ),
    )


def research_session_output(
    snapshot: ResearchSessionSnapshot,
    *,
    include_trajectory: bool = False,
) -> ResearchSessionOutput:
    state = snapshot.state
    latest = (
        research_run_output(state, include_trajectory=include_trajectory)
        if "run_id" in state
        else None
    )
    return ResearchSessionOutput(
        metadata=snapshot.metadata,
        checkpoint_id=snapshot.checkpoint_id,
        pending_nodes=snapshot.pending_nodes,
        resumable=snapshot.resumable,
        latest_run=latest,
    )
