from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _evaluate_context(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    if state["status"] is not AgentRunStatus.RUNNING:
        return _skipped("evaluate_context")
    plan = state.get("execution_plan")
    if plan is None:
        error = _validation_error("evaluate_context", "missing_execution_plan")
        return {
            "status": AgentRunStatus.FAILED,
            "errors": (error,),
            "trajectory": (_failed_event("evaluate_context", started),),
        }
    if plan.route is ResearchRoute.UNSUPPORTED:
        error = _agent_error(
            "evaluate_context",
            "unsupported_question",
            "The question is outside the supported research capabilities.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "errors": (error,),
            "trajectory": (
                _event(
                    "evaluate_context",
                    TrajectoryStatus.COMPLETED,
                    "Unsupported question was explicitly abstained.",
                    started,
                ),
            ),
        }

    issues: list[tuple[ExecutionBranch, str]] = []
    outcomes = {item.branch_id: item for item in state.get("branch_outcomes", ())}
    for branch in _source_branches(plan):
        outcome = outcomes.get(branch.branch_id)
        if outcome is None or outcome.status is BranchStatus.FAILED:
            issues.append((branch, "execution_failed"))
        elif not _branch_has_evidence(state, branch):
            issues.append((branch, "insufficient_evidence"))

    required = [(branch, reason) for branch, reason in issues if not branch.optional]
    optional = [(branch, reason) for branch, reason in issues if branch.optional]
    errors = tuple(
        _agent_error(
            "evaluate_context",
            f"{reason}_{branch.branch_id}",
            "A research branch returned insufficient usable evidence."
            if reason == "insufficient_evidence"
            else "A required research branch failed.",
            category=AgentErrorCategory.TOOL,
            severity=AgentErrorSeverity.TERMINAL,
        )
        for branch, reason in issues
        if reason == "insufficient_evidence"
    )
    update: dict[str, object] = {
        "trajectory": (
            _event(
                "evaluate_context",
                TrajectoryStatus.COMPLETED,
                "Source branch context was evaluated.",
                started,
                details={"issues": len(issues)},
            ),
        ),
    }
    if errors:
        update["errors"] = errors
    if required:
        execution_failure = any(reason == "execution_failed" for _, reason in required)
        update["status"] = AgentRunStatus.FAILED if execution_failure else AgentRunStatus.ABSTAINED
        if not execution_failure:
            financial_missing = tuple(
                branch
                for branch, reason in required
                if reason == "insufficient_evidence" and isinstance(branch, FinancialFactsBranch)
            )
            if financial_missing:
                update["draft_answer"] = _runtime_financial_missing_answer(
                    state,
                    financial_missing,
                )
    elif optional:
        if _has_any_source_evidence(state):
            update["status"] = AgentRunStatus.PARTIAL
        else:
            update["status"] = AgentRunStatus.ABSTAINED
    return update


def _runtime_financial_missing_answer(
    state: AgentState,
    branches: tuple[FinancialFactsBranch, ...],
) -> str:
    company = _runtime_financial_missing_company_label(state, branches)
    metrics = ", ".join(_runtime_financial_missing_metrics(branches))
    fallback_note = _runtime_financial_fallback_note(state, branches)
    if _looks_ukrainian(state["question"]):
        return (
            f"Не можу виконати цей запит для {company}: зараз CompanyLens підтримує тільки "
            "SEC/EDGAR companies і ті structured financial facts, які вже доступні після "
            f"підготовки даних. Для метрик {metrics} не знайшов потрібних фактів. "
            f"{fallback_note} Розрахунок і графік не будувалися, щоб не показати "
            "необґрунтований результат."
        )
    return (
        f"I cannot complete this request for {company}: CompanyLens currently supports only "
        "SEC/EDGAR companies and the structured financial facts available after data "
        f"preparation. I could not find the required facts for: {metrics}. {fallback_note} "
        "The calculation and chart were not produced so the result would not be unsupported."
    )


def _runtime_financial_missing_company_label(
    state: AgentState,
    branches: tuple[FinancialFactsBranch, ...],
) -> str:
    frame = state.get("research_frame")
    if frame is not None:
        return _readiness_company_label(frame)
    resolved = state.get("resolved_query")
    if resolved is not None:
        for entity in resolved.entities:
            if entity.candidates:
                return entity.candidates[0].display_value
            if entity.canonical_value:
                return entity.canonical_value
            if entity.mention:
                return entity.mention
    for branch in branches:
        if branch.request.tickers:
            return ", ".join(branch.request.tickers)
        if branch.request.company_ids:
            return ", ".join(str(company_id) for company_id in branch.request.company_ids)
    return "the resolved company"


def _runtime_financial_missing_metrics(
    branches: tuple[FinancialFactsBranch, ...],
) -> tuple[str, ...]:
    metrics: list[str] = []
    for branch in branches:
        metrics.extend(branch.request.metrics)
    return tuple(dict.fromkeys(metrics)) or ("financial facts",)


def _runtime_financial_fallback_note(
    state: AgentState,
    branches: tuple[FinancialFactsBranch, ...],
) -> str:
    warnings = _runtime_financial_missing_warnings(state, branches)
    ukrainian = _looks_ukrainian(state["question"])
    if "annual_financial_fallback_missing" in warnings:
        return (
            "Я також спробував annual fallback, але annual facts теж не знайшлися."
            if ukrainian
            else "I also tried the annual fallback, but annual facts were unavailable too."
        )
    if "annual_financial_fallback_failed" in warnings:
        return (
            "Annual fallback був спробуваний, але fallback query не виконався."
            if ukrainian
            else "The annual fallback was attempted, but the fallback query failed."
        )
    if _runtime_financial_requires_quarterly_data(state, branches):
        return (
            "Annual fallback не застосовувався, бо цей розрахунок потребує quarterly facts."
            if ukrainian
            else "Annual fallback was not used because this calculation requires quarterly facts."
        )
    return (
        "Annual fallback не застосовувався, бо його не можна безпечно використати для цього запиту."
        if ukrainian
        else "Annual fallback was not used because it was not safe for this request."
    )


def _runtime_financial_missing_warnings(
    state: AgentState,
    branches: tuple[FinancialFactsBranch, ...],
) -> set[str]:
    branch_ids = {branch.branch_id for branch in branches}
    warnings: set[str] = set()
    for result in state.get("financial_results", ()):
        if result.branch_id in branch_ids:
            warnings.update(result.result.warnings)
    return warnings


def _runtime_financial_requires_quarterly_data(
    state: AgentState,
    branches: tuple[FinancialFactsBranch, ...],
) -> bool:
    plan = state.get("execution_plan")
    if plan is None:
        return False
    branch_ids = {branch.branch_id for branch in branches}
    return any(
        isinstance(branch, CalculationBranch)
        and branch.operation == "quarter_over_quarter_growth"
        and bool(branch_ids.intersection(branch.input_refs))
        for branch in plan.branches
    )


__all__ = (
    "_evaluate_context",
    "_runtime_financial_missing_answer",
    "_runtime_financial_missing_company_label",
    "_runtime_financial_missing_metrics",
    "_runtime_financial_fallback_note",
    "_runtime_financial_missing_warnings",
    "_runtime_financial_requires_quarterly_data",
)  # noqa: E501
