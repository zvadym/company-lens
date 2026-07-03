from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _plan_request(state: AgentState, runtime: Runtime[ResearchAgentRuntime]) -> dict[str, object]:
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("plan_request")
    analysis = state.get("analysis")
    resolved = state.get("resolved_query")
    if analysis is None or resolved is None:
        missing_error = _validation_error("plan_request", "missing_planning_inputs")
        return {"status": AgentRunStatus.FAILED, "errors": (missing_error,)}
    started = time.monotonic()
    memory = state.get("session_memory")
    frame = _ensure_research_frame(
        state,
        analysis=analysis,
        resolved=resolved,
        memory=memory,
    )
    ambiguous_companies = _ambiguous_company_entities(resolved)
    if ambiguous_companies:
        ambiguity_error = _agent_error(
            "plan_request",
            "ambiguous_company",
            "The company mention matched multiple SEC companies and requires clarification.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (ambiguity_error,),
            "draft_answer": _ambiguous_company_answer(frame, ambiguous_companies),
            "research_frame": frame,
            "trajectory": (
                _event(
                    "plan_request",
                    TrajectoryStatus.COMPLETED,
                    "Question requires company clarification before planning.",
                    started,
                    details={"ambiguous_companies": len(ambiguous_companies)},
                ),
            ),
        }
    if _requires_financial_company(analysis) and not resolved.company_ids:
        missing_company_error = _agent_error(
            "plan_request",
            "missing_company",
            "The question requires company financial facts, but no company was resolved.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (missing_company_error,),
            "draft_answer": _missing_company_answer(frame),
            "research_frame": frame,
            "trajectory": (
                _event(
                    "plan_request",
                    TrajectoryStatus.COMPLETED,
                    "Question requires a company, but none was resolved.",
                    started,
                ),
            ),
        }
    try:
        frame = _probe_financial_readiness_if_needed(frame, runtime.context.tools)
    except ResearchToolError as exc:
        tool_error = exc.error.model_copy(update={"node": "plan_request"})
        return {
            "status": AgentRunStatus.FAILED,
            "errors": (tool_error,),
            "trajectory": (_failed_event("plan_request", started),),
        }
    missing_readiness = _missing_required_financial_readiness(frame)
    if missing_readiness:
        readiness_error = _financial_readiness_error(missing_readiness)
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (readiness_error,),
            "draft_answer": _financial_readiness_answer(frame, missing_readiness),
            "research_frame": frame,
            "trajectory": (
                _event(
                    "plan_request",
                    TrajectoryStatus.COMPLETED,
                    "Required structured financial facts were unavailable before planning.",
                    started,
                    details={"missing_readiness": len(missing_readiness)},
                ),
            ),
        }
    deterministic_plan = _deterministic_follow_up_plan(
        state["question"],
        analysis,
        resolved,
        memory,
    )
    if deterministic_plan is not None:
        deterministic_update = _validated_deterministic_plan_update(
            deterministic_plan,
            analysis,
            resolved,
            state["policy"],
            frame,
            runtime,
            started,
        )
        if deterministic_update is not None:
            return deterministic_update
    previous_plan = memory.last_execution_plan if memory is not None else None
    planning_context = json.dumps(
        {
            "question": state["question"],
            "analysis": analysis.model_dump(mode="json"),
            "resolved_query": resolved.model_dump(mode="json"),
            "research_frame": frame.model_dump(mode="json"),
            "policy": state["policy"].model_dump(mode="json"),
            "previous_plan": (
                previous_plan.model_dump(mode="json") if previous_plan is not None else None
            ),
            "recent_artifacts": _planning_artifact_context(memory),
        },
        sort_keys=True,
    )
    messages = (
        _system_prompt_message(runtime, "agent/plan-request"),
        ModelMessage(role="user", content=planning_context),
    )
    output, attempts, error = _generate_structured_with_retries(
        runtime.context.model_provider,
        messages,
        ModelExecutionPlan,
        purpose=ModelPurpose.PLAN,
        max_retries=state["policy"].max_retries_per_node,
        node="plan_request",
    )
    update = _model_node_update("plan_request", attempts, started, error)
    if error is not None:
        fallback_plan = _planning_failure_fallback_plan(
            state["question"],
            analysis,
            resolved,
            memory,
        )
        if fallback_plan is not None:
            reconciled_analysis = _reconcile_analysis_with_plan(analysis, fallback_plan)
            try:
                plan = _normalize_and_validate_plan(
                    fallback_plan,
                    reconciled_analysis,
                    resolved,
                    state["policy"],
                    retrieval_index_name=runtime.context.retrieval_index_name,
                    retrieval_index_version=runtime.context.retrieval_index_version,
                )
            except ValueError:
                plan = None
            if plan is not None:
                update["execution_plan"] = plan
                update["research_frame"] = frame
                if reconciled_analysis != analysis:
                    update["analysis"] = reconciled_analysis
                return update
        update["status"] = _terminal_model_status(error)
        return update
    assert output is not None
    try:
        domain_plan = _canonicalize_plan_route(_domain_execution_plan(output))
        fallback_plan = _fallback_multi_company_growth_chart_plan(
            analysis,
            resolved,
            memory,
        )
        if fallback_plan is not None and _needs_multi_company_growth_chart_fallback(
            domain_plan,
            resolved,
        ):
            domain_plan = fallback_plan
        reconciled_analysis = _reconcile_analysis_with_plan(analysis, domain_plan)
        plan = _normalize_and_validate_plan(
            domain_plan,
            reconciled_analysis,
            resolved,
            state["policy"],
            retrieval_index_name=runtime.context.retrieval_index_name,
            retrieval_index_version=runtime.context.retrieval_index_version,
        )
    except ValueError as exc:
        fallback_plan = _planning_failure_fallback_plan(
            state["question"],
            analysis,
            resolved,
            memory,
        )
        if fallback_plan is not None:
            reconciled_analysis = _reconcile_analysis_with_plan(analysis, fallback_plan)
            try:
                plan = _normalize_and_validate_plan(
                    fallback_plan,
                    reconciled_analysis,
                    resolved,
                    state["policy"],
                    retrieval_index_name=runtime.context.retrieval_index_name,
                    retrieval_index_version=runtime.context.retrieval_index_version,
                )
            except ValueError:
                plan = None
            if plan is not None:
                update["execution_plan"] = plan
                update["research_frame"] = frame
                if reconciled_analysis != analysis:
                    update["analysis"] = reconciled_analysis
                return update
        validation_error = _agent_error(
            "plan_request",
            "invalid_execution_plan",
            f"The research workflow received an invalid execution plan: {exc}",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        update["errors"] = (validation_error,)
        update["status"] = AgentRunStatus.FAILED
        update["trajectory"] = (_failed_event("plan_request", started),)
        return update
    update["execution_plan"] = plan
    update["research_frame"] = frame
    if reconciled_analysis != analysis:
        update["analysis"] = reconciled_analysis
    return update


def _planning_failure_fallback_plan(
    question: str,
    analysis: QuestionAnalysis,
    resolved: ResolvedQuery,
    memory: SessionMemory | None,
) -> ExecutionPlan | None:
    return _deterministic_document_retrieval_plan(
        question,
        analysis,
        resolved,
    ) or _fallback_multi_company_growth_chart_plan(
        analysis,
        resolved,
        memory,
    )


__all__ = ("_plan_request",)
