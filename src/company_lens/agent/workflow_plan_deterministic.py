from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _requires_financial_company(analysis: QuestionAnalysis) -> bool:
    return AgentCapability.FINANCIAL_FACTS in analysis.required_capabilities


def _validated_deterministic_plan_update(
    deterministic_plan: ExecutionPlan,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    policy: ExecutionPolicy,
    frame: ResearchFrame,
    runtime: Runtime[ResearchAgentRuntime],
    started: float,
) -> dict[str, object] | None:
    reconciled_analysis = _reconcile_analysis_with_plan(analysis, deterministic_plan)
    try:
        plan = _normalize_and_validate_plan(
            deterministic_plan,
            reconciled_analysis,
            resolved,
            policy,
            retrieval_index_name=runtime.context.retrieval_index_name,
            retrieval_index_version=runtime.context.retrieval_index_version,
        )
    except ValueError:
        return None
    update: dict[str, object] = {
        "execution_plan": plan,
        "analysis": reconciled_analysis,
        "research_frame": frame,
        "node_attempts": (NodeAttempt(node="plan_request", attempts=1),),
        "trajectory": (
            _event(
                "plan_request",
                TrajectoryStatus.COMPLETED,
                "Replayed the previous execution plan with the user's explicit changes.",
                started,
            ),
        ),
    }
    return update


def _deterministic_follow_up_plan(
    question: str,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> ExecutionPlan | None:
    if memory is None or not analysis.is_follow_up:
        return None
    artifact_period_plan = _fallback_recent_artifact_period_plan(
        question,
        analysis,
        resolved,
        memory,
    )
    if artifact_period_plan is not None:
        return artifact_period_plan
    if memory.last_execution_plan is None or not _requests_plan_replay(question, analysis):
        return None
    return _replay_financial_follow_up_plan(
        question,
        analysis,
        resolved,
        memory.last_execution_plan,
    )


def _deterministic_document_retrieval_plan(
    question: str,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
) -> ExecutionPlan | None:
    if analysis.route is not ResearchRoute.RAG_ONLY:
        return None
    # Cross-document wording can make the parser add extra capabilities, but
    # a RAG-only route still needs at least one document source branch.
    if AgentCapability.DOCUMENTS not in analysis.required_capabilities:
        return None
    if not resolved.company_ids:
        return None
    return ExecutionPlan(
        route=ResearchRoute.RAG_ONLY,
        branches=(
            DocumentRetrievalBranch(
                branch_id="documents",
                request=AdaptiveRetrievalRequest(query=question),
            ),
        ),
        requires_citations=True,
        reason_codes=("deterministic_document_retrieval_plan",),
    )


__all__ = (
    "_requires_financial_company",
    "_validated_deterministic_plan_update",
    "_deterministic_follow_up_plan",
    "_deterministic_document_retrieval_plan",
)  # noqa: E501
