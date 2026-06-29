from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from company_lens import cli
from company_lens.agent.events import AgentExecutionEvent
from company_lens.agent.schemas import (
    AgentCapability,
    AgentRunStatus,
    AgentState,
    CalculationBranch,
    CompanyTarget,
    CompanyTargetSource,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialFactsBranch,
    NodeAttempt,
    QuestionAnalysis,
    ResearchFrame,
    ResearchRoute,
    TrajectoryEvent,
    TrajectoryStatus,
)
from company_lens.agent.workflow import create_initial_agent_state
from company_lens.config import Settings
from company_lens.evals.agent_runner import (
    observed_result_from_state,
    run_golden_agent_dataset,
)
from company_lens.evals.golden import load_golden_dataset
from company_lens.financials.schemas import FinancialFactQuery
from company_lens.observability.telemetry import record_generation
from company_lens.retrieval.adaptive_schemas import ResolvedQuery

GOLDEN_FOLLOW_UP_DATASET = Path("evals/datasets/golden/follow_up.v1.yaml")


class FakeGoldenAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, ExecutionPolicy]] = []

    def run(
        self,
        question: str,
        *,
        session_id: str,
        policy: ExecutionPolicy,
        observer: Callable[[AgentExecutionEvent], None] | None = None,
    ) -> AgentState:
        self.calls.append((question, session_id, policy))
        if observer is not None:
            observer(
                AgentExecutionEvent(
                    event_key="test:first",
                    event_type="analysis.summary",
                    data={"route": "calculation"},
                )
            )
        record_generation(
            model="gpt-test",
            purpose="planning",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            trace_content="metadata",
            cost_usd=0.002,
        )
        company = "Datadog" if "Datadog" in question else "Cloudflare"
        ticker = "DDOG" if company == "Datadog" else "NET"
        source: CompanyTargetSource = (
            "current_question" if "Datadog" in question else "follow_up_context"
        )
        return _completed_state(
            question,
            session_id=session_id,
            policy=policy,
            company=company,
            ticker=ticker,
            source=source,
        )


def test_golden_agent_runner_executes_follow_up_turns_in_one_session() -> None:
    dataset = load_golden_dataset(GOLDEN_FOLLOW_UP_DATASET)
    agent = FakeGoldenAgent()

    observed = run_golden_agent_dataset(
        dataset,
        agent,
        policy=ExecutionPolicy(max_tool_calls=4),
        case_ids=("followup_replace_company_preserve_task_001",),
        session_prefix="test-eval",
        run_token="fixed",
    )

    assert len(agent.calls) == 2
    assert {session_id for _, session_id, _ in agent.calls} == {
        "test-eval-fixed-followup_replace_company_preserve_task_001"
    }
    result = observed.results[0]
    assert result.case_id == "followup_replace_company_preserve_task_001"
    assert result.companies[0].mention == "Datadog"
    assert result.companies[0].ticker == "DDOG"
    assert result.operation == "year_over_year_growth"
    assert result.route == "calculation"
    assert result.tools == ("query_financial_facts", "calculate_metrics")
    assert result.operational is not None
    assert result.operational.tool_calls_used == 2
    assert result.operational.api_calls == 2
    assert result.operational.retry_count == 1
    assert result.operational.input_tokens == 20
    assert result.operational.output_tokens == 10
    assert result.operational.total_tokens == 30
    assert result.operational.cost_usd == 0.004
    assert result.operational.policy_max_tool_calls == 4
    assert result.operational.time_to_first_event_ms is not None
    assert [event.node for event in result.trajectory] == [
        "query_financial_facts",
        "calculate_metrics",
    ]


def test_run_golden_agent_cli_writes_observed_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = tmp_path / "golden.yaml"
    dataset_path.write_text(
        """
name: cli-live-golden
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
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "observed.json"
    agent = FakeGoldenAgent()
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(openai_api_key=SecretStr("test-key")),
    )
    monkeypatch.setattr(cli, "open_persistent_research_agent", _context_value(agent))

    exit_code = cli.main(
        [
            "run-golden-agent",
            "--dataset",
            str(dataset_path),
            "--output",
            str(output_path),
            "--max-tool-calls",
            "4",
            "--pretty",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["results"] == 1
    assert summary["output"] == str(output_path)
    assert payload["dataset_name"] == "cli-live-golden"
    assert payload["results"][0]["companies"][0]["ticker"] == "NET"
    assert payload["results"][0]["operational"]["tool_calls_used"] == 2
    assert payload["results"][0]["operational"]["total_tokens"] == 15
    assert agent.calls[0][2].max_tool_calls == 4


def test_observed_route_is_unsupported_for_ambiguous_target_without_plan() -> None:
    question = "Show revenue growth for United."
    analysis = QuestionAnalysis(
        normalized_question=question,
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    resolved = ResolvedQuery(query=question, metrics=("revenue",))
    frame = ResearchFrame(
        question=question,
        analysis=analysis,
        resolved_query=resolved,
        company_targets=(
            CompanyTarget(
                mention="United",
                ticker="UAC",
                status="ambiguous",
                source="current_question",
            ),
        ),
    )
    state = create_initial_agent_state(
        question,
        session_id="test-session",
        policy=ExecutionPolicy(max_tool_calls=4),
    )
    state.update(
        {
            "status": AgentRunStatus.COMPLETED,
            "analysis": analysis,
            "resolved_query": resolved,
            "research_frame": frame,
            "execution_plan": None,
        }
    )

    result = observed_result_from_state("ambiguous_united_revenue_growth_001", state)

    assert result.route == "unsupported"
    assert result.companies[0].status == "ambiguous"
    assert result.companies[0].ticker == "UAC"


def _completed_state(
    question: str,
    *,
    session_id: str,
    policy: ExecutionPolicy,
    company: str,
    ticker: str,
    source: CompanyTargetSource,
) -> AgentState:
    route = ResearchRoute.CALCULATION
    analysis = QuestionAnalysis(
        normalized_question=question,
        route=route,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    resolved = ResolvedQuery(query=question, metrics=("revenue",))
    plan = ExecutionPlan(
        route=route,
        branches=(
            FinancialFactsBranch(
                branch_id="facts",
                request=FinancialFactQuery(tickers=(ticker,), metrics=("revenue",)),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("facts",),
            ),
        ),
    )
    frame = ResearchFrame(
        question=question,
        analysis=analysis,
        resolved_query=resolved,
        company_targets=(
            CompanyTarget(
                mention=company,
                ticker=ticker,
                status="resolved",
                source=source,
            ),
        ),
    )
    state = create_initial_agent_state(question, session_id=session_id, policy=policy)
    state.update(
        {
            "status": AgentRunStatus.COMPLETED,
            "analysis": analysis,
            "resolved_query": resolved,
            "research_frame": frame,
            "execution_plan": plan,
            "tool_calls_used": 2,
            "repair_attempts": 0,
            "node_attempts": (
                NodeAttempt(node="query_financial_facts:facts", attempts=2),
                NodeAttempt(node="calculate_metrics:growth", attempts=1),
            ),
            "trajectory": (
                TrajectoryEvent(
                    node="query_financial_facts",
                    status=TrajectoryStatus.COMPLETED,
                    occurred_at=datetime.now(UTC),
                    summary="Facts queried.",
                    duration_ms=12,
                ),
                TrajectoryEvent(
                    node="calculate_metrics",
                    status=TrajectoryStatus.COMPLETED,
                    occurred_at=datetime.now(UTC),
                    summary="Growth calculated.",
                    duration_ms=3,
                ),
            ),
        }
    )
    return state


def _context_value(value: object) -> Any:
    @contextmanager
    def context(_: Settings) -> Iterator[object]:
        yield value

    return context
