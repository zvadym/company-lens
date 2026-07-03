from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _validate_citations(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    answer = state.get("draft_answer") or ""
    registry = EvidenceRegistry(state.get("evidence", ()))
    known = {item.evidence_id: item for item in registry.records()}
    plan = state.get("execution_plan")
    citations_required = plan.requires_citations if plan is not None else True
    claims = extract_claims(answer)
    validation = AnswerValidator(
        registry,
        semantic_judge=runtime.context.semantic_support_judge,
    ).validate(
        answer,
        citations_required=citations_required,
    )
    citations = tuple(
        CitationReference(
            evidence_id=item,
            label=known[item].summary[:120],
            claim_ids=tuple(claim.claim_id for claim in claims if item in claim.evidence_ids),
        )
        for item in validation.cited_evidence_ids
    )
    previews = registry.hydrate_sources(runtime.context.source_checker)
    semantic_results = tuple(
        claim.semantic_support for claim in validation.claims if claim.semantic_support is not None
    )
    record_validation(
        validator="citations",
        valid=validation.valid,
        issue_count=len(validation.issues),
    )
    return {
        "answer_validation": validation,
        "claims": claims,
        "citations": citations,
        "source_previews": previews,
        "trajectory": (
            _event(
                "validate_citations",
                TrajectoryStatus.COMPLETED if validation.valid else TrajectoryStatus.FAILED,
                (
                    "Claim evidence validated."
                    if validation.valid
                    else "Claim evidence was invalid."
                ),
                started,
                details={
                    "claims": len(claims),
                    "citations": len(citations),
                    "issues": len(validation.issues),
                    "semantic_supported": sum(
                        item.status is SemanticSupportStatus.SUPPORTED for item in semantic_results
                    ),
                    "semantic_unsupported": sum(
                        item.status is SemanticSupportStatus.UNSUPPORTED
                        for item in semantic_results
                    ),
                    "semantic_unavailable": sum(
                        item.status is SemanticSupportStatus.UNAVAILABLE
                        for item in semantic_results
                    ),
                },
            ),
        ),
    }


def _route_after_validation(
    state: AgentState,
) -> Literal["finalize_response", "repair_or_abstain"]:
    validation = state.get("answer_validation")
    return (
        "finalize_response"
        if validation is not None and validation.valid
        else ("repair_or_abstain")
    )


def _repair_or_abstain(
    state: AgentState, runtime: Runtime[ResearchAgentRuntime]
) -> dict[str, object]:
    started = time.monotonic()
    attempts_used = state.get("repair_attempts", 0)
    if attempts_used >= state["policy"].max_repair_attempts:
        fallback_update = _citation_fallback_update(state, started)
        if fallback_update is not None:
            return fallback_update
        exhausted_error = _agent_error(
            "repair_or_abstain",
            "citation_repair_exhausted",
            "The answer could not be repaired within the configured limit.",
            category=AgentErrorCategory.BUDGET,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (exhausted_error,),
            "trajectory": (_failed_event("repair_or_abstain", started),),
        }
    validation = state.get("answer_validation")
    evidence_ids = [item.evidence_id for item in state.get("evidence", ())]
    messages = (
        _system_prompt_message(runtime, "agent/repair-answer"),
        ModelMessage(
            role="user",
            content=json.dumps(
                {
                    "draft": state.get("draft_answer"),
                    "validation_reason_codes": validation.reason_codes if validation else (),
                    "validation_issues": (
                        [issue.model_dump(mode="json") for issue in validation.issues]
                        if validation
                        else []
                    ),
                    "invalid_claims": _invalid_claim_previews(
                        state.get("claims", ()),
                        validation.issues if validation else (),
                    ),
                    "evidence": _compact_evidence_context(state.get("evidence", ())),
                    "allowed_evidence_ids": evidence_ids,
                },
                sort_keys=True,
            ),
        ),
    )
    text, attempts, error = _generate_text_with_retries(
        runtime.context.model_provider,
        messages,
        purpose=ModelPurpose.REPAIR,
        # Repair has its own attempt budget. A provider timeout must not multiply the general
        # node retry budget and hold a run open for several minutes.
        max_retries=0,
        node="repair_or_abstain",
    )
    update = _model_node_update("repair_or_abstain", attempts, started, error)
    update["repair_attempts"] = attempts_used + 1
    if error is not None:
        fallback_update = _citation_fallback_update(state, started)
        if fallback_update is not None:
            return {
                **fallback_update,
                "repair_attempts": attempts_used + 1,
                "errors": update.get("errors", ()),
            }
        update["status"] = AgentRunStatus.ABSTAINED
    else:
        update["draft_answer"] = _normalize_answer_number_formatting(text or "")
    return update


def _citation_fallback_update(
    state: AgentState,
    started: float,
) -> dict[str, object] | None:
    fallback = _deterministic_fallback_answer(state.get("evidence", ()))
    if fallback is None or fallback == state.get("draft_answer"):
        return None
    return {
        "draft_answer": fallback,
        "trajectory": (
            _event(
                "repair_or_abstain",
                TrajectoryStatus.COMPLETED,
                "Used deterministic cited fallback answer.",
                started,
                details={"fallback": "deterministic_evidence"},
            ),
        ),
    }


__all__ = (
    "_validate_citations",
    "_route_after_validation",
    "_repair_or_abstain",
    "_citation_fallback_update",
)  # noqa: E501
