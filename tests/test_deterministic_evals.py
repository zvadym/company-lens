from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from company_lens import cli
from company_lens.evals.deterministic import (
    evaluate_golden_results,
    load_regression_gate,
)

GOLDEN_CORE_DATASET = Path("evals/datasets/golden/core.v1.yaml")
GOLDEN_FOLLOW_UP_DATASET = Path("evals/datasets/golden/follow_up.v1.yaml")
EVAL_FAST_GATE = Path("evals/gates/eval-fast.v1.yaml")
EVAL_FULL_GATE = Path("evals/gates/eval-full.v1.yaml")


def test_deterministic_core_results_pass_strict_gate(tmp_path: Path) -> None:
    results_path = _write_results(tmp_path, _core_results())
    gate = load_regression_gate(EVAL_FAST_GATE)

    report = evaluate_golden_results(GOLDEN_CORE_DATASET, results_path, gate=gate)

    assert report.passed is True
    assert report.failed_cases == 0
    assert report.metrics.case_pass_rate == 1.0
    assert report.metrics.required_tool_recall == 1.0
    assert report.metrics.prohibited_tool_pass_rate == 1.0
    assert {category.category: category.failed for category in report.categories} == {
        "structured_financial": 0,
        "document_retrieval": 0,
        "hybrid": 0,
        "ambiguous_entity": 0,
        "missing_data_or_abstention": 0,
        "adversarial_or_prompt_injection": 0,
        "cross_document_comparison": 0,
    }


def test_deterministic_evaluator_reports_missing_results(tmp_path: Path) -> None:
    payload = _core_results()
    payload["results"] = payload["results"][:-1]
    results_path = _write_results(tmp_path, payload)

    report = evaluate_golden_results(GOLDEN_CORE_DATASET, results_path)

    assert report.passed is False
    assert report.missing_results == ("crossdoc_cloudflare_risks_2024_2025_001",)
    assert report.metrics.missing_result_rate == 0.142857


def test_regression_gate_reports_threshold_failures(tmp_path: Path) -> None:
    payload = _core_results()
    payload["results"] = payload["results"][:-1]
    results_path = _write_results(tmp_path, payload)
    gate = load_regression_gate(EVAL_FAST_GATE)

    report = evaluate_golden_results(GOLDEN_CORE_DATASET, results_path, gate=gate)

    assert report.passed is False
    assert report.gate is not None
    assert {failure.metric for failure in report.gate.failures} >= {
        "case_pass_rate",
        "missing_result_rate",
    }


def test_operational_budgets_pass_when_observed_metrics_are_within_limits(
    tmp_path: Path,
) -> None:
    payload = _core_results()
    payload["results"][0]["operational"] = _operational_metrics()
    payload["results"] = payload["results"][:1]
    dataset_path = _write_single_case_dataset(tmp_path)
    results_path = _write_results(tmp_path, payload)
    gate = load_regression_gate(EVAL_FULL_GATE)

    report = evaluate_golden_results(dataset_path, results_path, gate=gate)

    assert report.passed is True
    assert report.metrics.operational_metrics_presence_rate == 1.0
    assert report.metrics.operational_budget_pass_rate == 1.0


def test_operational_budget_failures_are_reported_per_case(tmp_path: Path) -> None:
    payload = _core_results()
    operational = _operational_metrics()
    operational["tool_calls_used"] = 11
    payload["results"][0]["operational"] = operational
    payload["results"] = payload["results"][:1]
    dataset_path = _write_single_case_dataset(tmp_path)
    results_path = _write_results(tmp_path, payload)
    gate = load_regression_gate(EVAL_FULL_GATE)

    report = evaluate_golden_results(dataset_path, results_path, gate=gate)

    failed_case = report.cases[0]
    assert report.passed is False
    assert failed_case.checks["operational_budgets"] is False
    assert any("tool calls was 11" in failure for failure in failed_case.failures)


def test_operational_gate_requires_metrics_when_configured(tmp_path: Path) -> None:
    payload = _core_results()
    payload["results"] = payload["results"][:1]
    dataset_path = _write_single_case_dataset(tmp_path)
    results_path = _write_results(tmp_path, payload)
    gate = load_regression_gate(EVAL_FULL_GATE)

    report = evaluate_golden_results(dataset_path, results_path, gate=gate)

    assert report.passed is False
    assert report.metrics.operational_metrics_presence_rate == 0.0
    assert report.cases[0].failures == ("missing operational metrics",)


def test_deterministic_evaluator_reports_route_and_tool_failures(tmp_path: Path) -> None:
    payload = copy.deepcopy(_core_results())
    first = payload["results"][0]
    first["route"] = "rag_only"
    first["tools"] = ["query_financial_facts", "retrieve_documents"]
    results_path = _write_results(tmp_path, payload)

    report = evaluate_golden_results(GOLDEN_CORE_DATASET, results_path)

    failed_case = report.cases[0]
    assert report.passed is False
    assert failed_case.checks["route"] is False
    assert failed_case.checks["prohibited_tools"] is False
    assert any("route was rag_only" in failure for failure in failed_case.failures)
    assert any(
        "used prohibited tools: retrieve_documents" in failure for failure in failed_case.failures
    )


def test_required_tools_can_be_checked_from_trajectory(tmp_path: Path) -> None:
    payload = copy.deepcopy(_core_results())
    first = payload["results"][0]
    first["tools"] = []
    first["trajectory"] = [{"node": "query_financial_facts", "status": "completed"}]
    results_path = _write_results(tmp_path, payload)

    report = evaluate_golden_results(GOLDEN_CORE_DATASET, results_path)

    assert report.passed is True
    assert report.cases[0].checks["required_tools"] is True


def test_follow_up_results_pass_safety_checks(tmp_path: Path) -> None:
    results_path = _write_results(tmp_path, _follow_up_results())

    report = evaluate_golden_results(GOLDEN_FOLLOW_UP_DATASET, results_path)

    assert report.passed is True
    assert report.metrics.follow_up_safety_accuracy == 1.0


def test_follow_up_reuse_of_prohibited_company_fails(tmp_path: Path) -> None:
    payload = copy.deepcopy(_follow_up_results())
    replace_case = payload["results"][1]
    replace_case["companies"].append(
        {
            "mention": "Cloudflare",
            "status": "resolved",
            "ticker": "NET",
            "source": "follow_up_context",
        }
    )
    results_path = _write_results(tmp_path, payload)

    report = evaluate_golden_results(GOLDEN_FOLLOW_UP_DATASET, results_path)

    failed_case = report.cases[1]
    assert report.passed is False
    assert failed_case.checks["follow_up_safety"] is False
    assert any(
        "reused prohibited follow-up companies: cloudflare" in failure
        for failure in failed_case.failures
    )


def test_cli_evaluates_results_and_writes_markdown_report(
    tmp_path: Path,
    capsys: Any,
) -> None:
    results_path = _write_results(tmp_path, _core_results())
    markdown_path = tmp_path / "report.md"

    exit_code = cli.main(
        [
            "evaluate-golden-results",
            "--dataset",
            str(GOLDEN_CORE_DATASET),
            "--results",
            str(results_path),
            "--gate",
            str(EVAL_FAST_GATE),
            "--markdown-output",
            str(markdown_path),
            "--pretty",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"passed": true' in output
    assert "Deterministic Evaluation Report" in markdown_path.read_text(encoding="utf-8")


def _write_results(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "observed-results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_single_case_dataset(tmp_path: Path) -> Path:
    path = tmp_path / "single-case.yaml"
    path.write_text(
        """
name: company-lens-core-golden
version: 1
cases:
  - id: structured_cloudflare_revenue_2025_001
    category: structured_financial
    conversation:
      - role: user
        content: What was Cloudflare revenue in fiscal 2025?
    expected:
      companies:
        - mention: Cloudflare
          status: resolved
          ticker: NET
          source: current_question
      metrics:
        - revenue
      route:
        expected_route: structured_only
        required_tools:
          - query_financial_facts
        prohibited_tools:
          - retrieve_documents
""",
        encoding="utf-8",
    )
    return path


def _operational_metrics() -> dict[str, Any]:
    return {
        "total_latency_ms": 100,
        "time_to_first_event_ms": 10,
        "node_latencies": [
            {"node": "query_financial_facts", "duration_ms": 20},
        ],
        "tool_calls_used": 1,
        "repair_attempts": 0,
        "api_calls": 1,
        "retry_count": 0,
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "node_attempts": [
            {"node": "query_financial_facts", "attempts": 1},
        ],
        "policy_max_tool_calls": 10,
        "policy_max_repair_attempts": 1,
        "policy_max_retries_per_node": 2,
    }


def _core_results() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_name": "company-lens-core-golden",
        "dataset_version": 1,
        "results": [
            {
                "case_id": "structured_cloudflare_revenue_2025_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "route": "structured_only",
                "tools": ["query_financial_facts"],
            },
            {
                "case_id": "document_cloudflare_2025_risk_factors_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "current_question",
                    }
                ],
                "route": "rag_only",
                "tools": ["retrieve_documents"],
            },
            {
                "case_id": "hybrid_cloudflare_growth_and_risks_2025_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "operation": "year_over_year_growth",
                "route": "hybrid",
                "tools": ["query_financial_facts", "calculate_metrics", "retrieve_documents"],
            },
            {
                "case_id": "ambiguous_united_revenue_growth_001",
                "companies": [
                    {
                        "mention": "United",
                        "status": "ambiguous",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "route": "unsupported",
            },
            {
                "case_id": "abstention_cloudflare_revenue_2035_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "route": "unsupported",
            },
            {
                "case_id": "adversarial_cloudflare_revenue_without_citations_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "route": "structured_only",
                "tools": ["query_financial_facts", "validate_citations"],
            },
            {
                "case_id": "crossdoc_cloudflare_risks_2024_2025_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "current_question",
                    }
                ],
                "route": "rag_only",
                "tools": ["retrieve_documents"],
            },
        ],
    }


def _follow_up_results() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_name": "company-lens-follow-up-golden",
        "dataset_version": 1,
        "results": [
            {
                "case_id": "followup_safe_inheritance_chart_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "follow_up_context",
                    }
                ],
                "metrics": ["revenue"],
                "route": "calculation",
                "tools": ["query_financial_facts", "calculate_metrics", "generate_chart_spec"],
            },
            {
                "case_id": "followup_replace_company_preserve_task_001",
                "companies": [
                    {
                        "mention": "Datadog",
                        "status": "resolved",
                        "ticker": "DDOG",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "route": "calculation",
                "tools": ["query_financial_facts", "calculate_metrics"],
            },
            {
                "case_id": "followup_add_company_to_comparison_001",
                "companies": [
                    {
                        "mention": "Cloudflare",
                        "status": "resolved",
                        "ticker": "NET",
                        "source": "follow_up_context",
                    },
                    {
                        "mention": "Datadog",
                        "status": "resolved",
                        "ticker": "DDOG",
                        "source": "follow_up_context",
                    },
                    {
                        "mention": "MongoDB",
                        "status": "resolved",
                        "ticker": "MDB",
                        "source": "current_question",
                    },
                ],
                "metrics": ["revenue"],
                "route": "calculation",
                "tools": ["query_financial_facts", "calculate_metrics"],
            },
            {
                "case_id": "followup_unresolved_company_no_previous_reuse_001",
                "companies": [
                    {
                        "mention": "Globex",
                        "status": "unresolved",
                        "source": "current_question",
                    }
                ],
                "metrics": ["revenue"],
                "route": "unsupported",
            },
        ],
    }
