from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from company_lens.evals.case_checks import evaluate_case
from company_lens.evals.checks import evaluate_dataset
from company_lens.evals.gates import EvaluationGate
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase
from company_lens.evals.langfuse_mapping import item_uuid, score_uuid
from company_lens.evals.langfuse_scores import ReconciledScoreConfigs
from company_lens.evals.manifest import DatasetSnapshot
from company_lens.evals.models import (
    CaseEvaluationRecord,
    CaseObservation,
    DatasetEvaluationRun,
    ObservedGoldenResults,
)
from company_lens.evals.observation import observed_result_from_observation
from company_lens.evals.score_contract import ScoreContract


class LangfuseExperimentError(RuntimeError):
    pass


def run_dataset_experiment(
    client: Any,
    dataset_client: Any,
    dataset: GoldenDataset,
    cases: tuple[GoldenDatasetCase, ...],
    *,
    snapshot: DatasetSnapshot,
    execution_id: str,
    commit_sha: str,
    manifest_fingerprint: str,
    score_contract: ScoreContract,
    score_bindings: ReconciledScoreConfigs,
    execute_case: Callable[[GoldenDatasetCase], CaseObservation],
    gate: EvaluationGate | None = None,
    max_concurrency: int = 1,
) -> DatasetEvaluationRun:
    if not cases:
        raise LangfuseExperimentError("no_selected_cases")
    case_by_id = {case.id: case for case in cases}
    expected_item_ids = {item_uuid(dataset.name, case.id) for case in cases}
    selected_items = [
        item for item in _items(dataset_client) if str(_value(item, "id")) in expected_item_ids
    ]
    if {str(_value(item, "id")) for item in selected_items} != expected_item_ids:
        raise LangfuseExperimentError("selected_snapshot_items_missing")
    # DatasetClient.run_experiment consumes its local pinned item collection. Narrowing this
    # freshly fetched client preserves the recorded version while supporting per-dataset limits.
    dataset_client.items = selected_items

    def task(*, item: Any, **_: Any) -> dict[str, Any]:
        metadata = _value(item, "metadata") or {}
        case_id = metadata.get("case_id")
        case = case_by_id.get(str(case_id))
        if case is None:
            return {"infrastructure_failure": "unknown_dataset_item"}
        return execute_case(case).model_dump(mode="json")

    short_sha = commit_sha[:7]
    run_name = f"company-lens-{dataset.name}-{short_sha}-{execution_id[:8]}"
    result = dataset_client.run_experiment(
        name=run_name,
        run_name=run_name,
        task=task,
        evaluators=[],
        max_concurrency=max_concurrency,
        metadata={
            "evaluation_execution_id": execution_id,
            "manifest_fingerprint": manifest_fingerprint,
            "dataset_version_timestamp": snapshot.version_timestamp.isoformat(),
        },
    )
    run_id = str(_value(result, "dataset_run_id") or "")
    if not run_id:
        raise LangfuseExperimentError("dataset_run_link_missing")

    item_results = list(_value(result, "item_results") or ())
    by_item_id = {_result_item_id(item): item for item in item_results}
    records: list[CaseEvaluationRecord] = []
    observations: list[CaseObservation] = []
    infrastructure_failure = set(by_item_id) != expected_item_ids
    for case in cases:
        item_id = item_uuid(dataset.name, case.id)
        item_result = by_item_id.get(item_id)
        if item_result is None:
            infrastructure_failure = True
            records.append(_infrastructure_record(case, "experiment_item_missing"))
            continue
        try:
            observation = CaseObservation.model_validate(_value(item_result, "output"))
        except (TypeError, ValueError):
            infrastructure_failure = True
            records.append(_infrastructure_record(case, "experiment_output_invalid"))
            continue
        if observation.case_id != case.id or observation.outcome == "infrastructure_error":
            infrastructure_failure = True
            records.append(
                _infrastructure_record(
                    case,
                    observation.failure_code or "experiment_case_mismatch",
                )
            )
            continue
        record = _evaluate_observation(case, observation, gate=gate)
        records.append(record)
        observations.append(observation)
        _publish_item_scores(
            client,
            run_id,
            str(_value(item_result, "trace_id") or ""),
            case,
            record,
            score_contract,
            score_bindings,
        )

    if infrastructure_failure or len(observations) != len(cases):
        _publish_score(
            client,
            score_id=score_uuid(run_id, "run", "gate_status"),
            name="gate_status",
            value="not_evaluated",
            config_id=score_bindings.id_for("gate_status"),
            dataset_run_id=run_id,
            comment="infrastructure_incomplete",
        )
        client.flush()
        return DatasetEvaluationRun(
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            snapshot=snapshot,
            status="partial",
            gate_status="not_evaluated",
            selected_case_ids=tuple(case.id for case in cases),
            case_results=tuple(records),
            langfuse_dataset_run_id=run_id,
            langfuse_run_url=_optional_str(_value(result, "dataset_run_url")),
        )

    observed = ObservedGoldenResults(
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        results=tuple(observed_result_from_observation(item) for item in observations),
    )
    selected_dataset = dataset.model_copy(update={"cases": cases})
    deterministic_report = evaluate_dataset(selected_dataset, observed, gate=gate)
    aggregate_scores = _aggregate_scores(cases, records, deterministic_report)
    gate_status: Literal["passed", "failed"] = (
        "passed" if all(record.passed for record in records) else "failed"
    )
    if gate is not None and not deterministic_report.passed:
        gate_status = "failed"
    aggregate_scores["gate_status"] = gate_status
    for definition in score_contract.scores:
        if definition.scope != "run":
            continue
        value = aggregate_scores[definition.name]
        _publish_score(
            client,
            score_id=score_uuid(run_id, "run", definition.name),
            name=definition.name,
            value=value,
            config_id=score_bindings.id_for(definition.name),
            dataset_run_id=run_id,
            comment="trusted_aggregate",
        )
    client.flush()
    return DatasetEvaluationRun(
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        snapshot=snapshot,
        status="completed",
        gate_status=gate_status,
        selected_case_ids=tuple(case.id for case in cases),
        case_results=tuple(records),
        aggregate_scores={
            name: float(value) for name, value in aggregate_scores.items() if name != "gate_status"
        },
        langfuse_dataset_run_id=run_id,
        langfuse_run_url=_optional_str(_value(result, "dataset_run_url")),
    )


def _evaluate_observation(
    case: GoldenDatasetCase,
    observation: CaseObservation,
    *,
    gate: EvaluationGate | None,
) -> CaseEvaluationRecord:
    evaluated = evaluate_case(case, observed_result_from_observation(observation), gate=gate)
    checks = dict(evaluated.checks)
    if case.citation_mode == "required":
        checks["citation"] = observation.citation.valid is True
    scores: dict[str, bool | float | str] = {
        "company_pass": checks["companies"],
        "metric_pass": checks["metrics"],
        "operation_pass": checks["operation"],
        "route_pass": checks["route"],
    }
    if case.expected.route.required_tools:
        scores["required_tools_pass"] = checks["required_tools"]
    if case.expected.route.prohibited_tools:
        scores["prohibited_tools_pass"] = checks["prohibited_tools"]
    if case.expected.follow_up is not None:
        scores["follow_up_safety_pass"] = checks["follow_up_safety"]
    if case.citation_mode == "required":
        scores["citation_valid"] = checks["citation"]
    if "operational_budgets" in checks:
        scores["operational_budget_pass"] = checks["operational_budgets"]
    passed = all(checks.values())
    scores["case_pass"] = passed
    return CaseEvaluationRecord(
        case_id=case.id,
        category=case.category,
        passed=passed,
        checks=checks,
        failure_codes=tuple(
            sorted(f"{name}_failed" for name, value in checks.items() if not value)
        ),
        scores=scores,
    )


def _infrastructure_record(case: GoldenDatasetCase, code: str) -> CaseEvaluationRecord:
    return CaseEvaluationRecord(
        case_id=case.id,
        category=case.category,
        passed=None,
        failure_codes=(code,),
    )


def _publish_item_scores(
    client: Any,
    run_id: str,
    trace_id: str,
    case: GoldenDatasetCase,
    record: CaseEvaluationRecord,
    contract: ScoreContract,
    bindings: ReconciledScoreConfigs,
) -> None:
    definitions = {item.name: item for item in contract.scores if item.scope == "item"}
    for name, value in record.scores.items():
        definition = definitions[name]
        _publish_score(
            client,
            score_id=score_uuid(run_id, "item", name, case.id),
            name=name,
            value=value,
            config_id=bindings.id_for(name),
            trace_id=trace_id,
            comment="check_passed" if bool(value) else f"{name}_failed",
            data_type=definition.data_type,
        )


def _aggregate_scores(
    cases: tuple[GoldenDatasetCase, ...],
    records: list[CaseEvaluationRecord],
    report: Any,
) -> dict[str, float | str]:
    values: dict[str, float | str] = dict(report.metrics.model_dump())
    citation = [
        bool(record.scores["citation_valid"])
        for record in records
        if "citation_valid" in record.scores
    ]
    values["citation_validity_pass_rate"] = _ratio(sum(citation), len(citation))
    category_scores = {row.category: row.pass_rate for row in report.categories}
    category_names = {
        "document_retrieval": "category_document_retrieval",
        "structured_financial": "category_structured_financial",
        "hybrid": "category_hybrid",
        "cross_document_comparison": "category_cross_document",
        "ambiguous_entity": "category_ambiguous_entity",
        "missing_data_or_abstention": "category_missing_or_abstain",
        "adversarial_or_prompt_injection": "category_adversarial",
        "follow_up": "category_follow_up",
    }
    for category, score_name in category_names.items():
        values[score_name] = category_scores.get(category, 1.0)
    return values


def _publish_score(
    client: Any,
    *,
    score_id: str,
    name: str,
    value: bool | float | str,
    config_id: str,
    comment: str,
    trace_id: str | None = None,
    dataset_run_id: str | None = None,
    data_type: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "score_id": score_id,
        "name": name,
        "value": value,
        "config_id": config_id,
        "comment": comment,
    }
    if trace_id:
        payload["trace_id"] = trace_id
    if dataset_run_id:
        payload["dataset_run_id"] = dataset_run_id
    if data_type:
        payload["data_type"] = data_type
    client.create_score(**payload)


def _result_item_id(result: Any) -> str:
    direct = _value(result, "dataset_item_id")
    if direct:
        return str(direct)
    return str(_value(_value(result, "item"), "id") or "")


def _items(dataset_client: Any) -> list[Any]:
    return list(_value(dataset_client, "items") or ())


def _optional_str(value: Any) -> str | None:
    return str(value) if value else None


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
