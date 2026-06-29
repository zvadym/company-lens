from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _dispatch_calculation_branches(state: AgentState) -> list[Send] | str:
    if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}:
        return "finalize_response"
    plan = state.get("execution_plan")
    if plan is None:
        return "finalize_response"
    branches = [branch for branch in plan.branches if isinstance(branch, CalculationBranch)]
    return [
        Send("calculate_metrics", {**state, "active_branch": branch}) for branch in branches
    ] or ("generate_chart_spec")


def _calculate_metrics(state: AgentState) -> dict[str, object]:
    branch = cast(CalculationBranch, state["active_branch"])
    started = time.monotonic()
    try:
        result = _execute_calculation(branch, state)
        result = _normalize_calculation_result(branch, result, state)
    except (ValueError, TypeError, ArithmeticError):
        error = _agent_error(
            "calculate_metrics",
            "calculation_invalid_inputs",
            "A deterministic calculation could not be completed from its typed inputs.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "branch_outcomes": (
                BranchOutcome(
                    branch_id=branch.branch_id,
                    kind=branch.kind,
                    status=BranchStatus.FAILED,
                    optional=branch.optional,
                    attempts=1,
                    error=error,
                ),
            ),
            "errors": (error,),
            "node_attempts": (
                NodeAttempt(node=f"calculate_metrics:{branch.branch_id}", attempts=1),
            ),
            "trajectory": (_failed_event("calculate_metrics", started),),
        }
    return {
        "calculations": (CalculationBranchResult(branch_id=branch.branch_id, result=result),),
        "branch_outcomes": (
            BranchOutcome(
                branch_id=branch.branch_id,
                kind=branch.kind,
                status=BranchStatus.COMPLETED,
                optional=branch.optional,
                attempts=1,
            ),
        ),
        "node_attempts": (NodeAttempt(node=f"calculate_metrics:{branch.branch_id}", attempts=1),),
        "trajectory": (
            _event(
                "calculate_metrics",
                TrajectoryStatus.COMPLETED,
                "Deterministic calculation completed.",
                started,
                details={"branch_id": branch.branch_id},
            ),
        ),
    }


def _generate_chart_spec(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}:
        return _skipped("generate_chart_spec")
    plan = state.get("execution_plan")
    if plan is None:
        return {"status": AgentRunStatus.FAILED}

    calculation_issues = _failed_planned_branches(state, CalculationBranch)
    required_calculation_issues = [item for item in calculation_issues if not item.optional]
    if required_calculation_issues:
        return {
            "status": AgentRunStatus.FAILED,
            "trajectory": (_failed_event("generate_chart_spec", started),),
        }
    update: dict[str, object] = {}
    if calculation_issues:
        update["status"] = AgentRunStatus.PARTIAL

    chart = next((branch for branch in plan.branches if isinstance(branch, ChartBranch)), None)
    if chart is None:
        update["trajectory"] = (
            _event(
                "generate_chart_spec",
                TrajectoryStatus.SKIPPED,
                "No chart was requested.",
                started,
            ),
        )
        return update
    try:
        dataset = _chart_dataset_for_branch(chart, state)
        if (
            chart.chart_type in {"line", "area"}
            and len(dataset.series) > 1
            and len(dataset.points) < MIN_LINE_CHART_POINTS
        ):
            error = _agent_error(
                "generate_chart_spec",
                "insufficient_chart_points",
                "A line chart requires at least three aligned data points.",
                category=AgentErrorCategory.VALIDATION,
                severity=AgentErrorSeverity.RECOVERABLE,
            )
            update.update(
                {
                    "status": AgentRunStatus.PARTIAL,
                    "errors": (error,),
                    "trajectory": (
                        _event(
                            "generate_chart_spec",
                            TrajectoryStatus.COMPLETED,
                            "Skipped chart with too few aligned data points.",
                            started,
                            details={"point_count": len(dataset.points)},
                        ),
                    ),
                }
            )
            return update
        specification = generate_chart_specification(
            dataset,
            chart_type=chart.chart_type,
            title=_chart_title(chart, dataset, plan),
            x_label=chart.x_label,
        )
    except (ValueError, TypeError):
        error = _agent_error(
            "generate_chart_spec",
            "invalid_chart_dataset",
            "The selected result cannot be represented as a validated chart dataset.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        update.update(
            {
                "status": AgentRunStatus.PARTIAL if chart.optional else AgentRunStatus.FAILED,
                "errors": (error,),
                "trajectory": (_failed_event("generate_chart_spec", started),),
            }
        )
        return update
    update.update(
        {
            "chart_spec": specification,
            "trajectory": (
                _event(
                    "generate_chart_spec",
                    TrajectoryStatus.COMPLETED,
                    "Validated chart specification generated.",
                    started,
                ),
            ),
        }
    )
    return update


def _chart_title(
    chart: ChartBranch,
    dataset: ValidatedChartDataset,
    plan: ExecutionPlan,
) -> str:
    if "deterministic_follow_up_replay_plan" not in plan.reason_codes:
        return chart.title
    if len(dataset.series) == 1:
        return dataset.series[0].label
    return _comparison_chart_title(dataset)


def _comparison_chart_title(dataset: ValidatedChartDataset) -> str:
    labels = [series.label for series in dataset.series]
    if labels and all(" revenue " in f" {label.casefold()} " for label in labels):
        suffix = "YoY" if all("yoy" in label.casefold() for label in labels) else "comparison"
        return f"Revenue {suffix} comparison"
    return "Comparison chart"


def _route_after_chart(state: AgentState) -> Literal["merge_evidence", "finalize_response"]:
    if state["status"] in {AgentRunStatus.FAILED, AgentRunStatus.ABSTAINED}:
        return "finalize_response"
    return "merge_evidence"


def _merge_evidence(state: AgentState) -> dict[str, object]:
    started = time.monotonic()
    evidence = _evidence_from_state(state)
    if not evidence:
        error = _agent_error(
            "merge_evidence",
            "no_usable_evidence",
            "No usable evidence was available for answer generation.",
            category=AgentErrorCategory.VALIDATION,
            severity=AgentErrorSeverity.TERMINAL,
        )
        return {
            "status": AgentRunStatus.ABSTAINED,
            "evidence": (),
            "errors": (error,),
            "trajectory": (_failed_event("merge_evidence", started),),
        }
    return {
        "evidence": evidence,
        "trajectory": (
            _event(
                "merge_evidence",
                TrajectoryStatus.COMPLETED,
                "Typed evidence was merged.",
                started,
                details={"evidence_count": len(evidence)},
            ),
        ),
    }

__all__ = ('_dispatch_calculation_branches', '_calculate_metrics', '_generate_chart_spec', '_chart_title', '_comparison_chart_title', '_route_after_chart', '_merge_evidence')  # noqa: E501
