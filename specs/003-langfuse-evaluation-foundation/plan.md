# Implementation Plan: Langfuse Evaluation Foundation

**Branch**: `003-langfuse-evaluation-foundation` | **Date**: 2026-07-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-langfuse-evaluation-foundation/spec.md`

## Summary

Extend the existing repository-authored golden datasets and deterministic evaluator into a
manual, fail-closed evaluation execution that synchronizes exact dataset snapshots to Langfuse,
runs one Langfuse experiment per selected repository dataset, publishes versioned item/run scores,
and produces privacy-safe JSON, Markdown, and optional PR-comment summaries. The implementation
reuses the current live agent runner, `AnswerValidation`, operational metrics, PostgreSQL-backed
research sessions, and versioned YAML gates. It adds a typed orchestration layer, Langfuse adapter,
score contract, citation applicability, exact snapshot manifest, and explicit separation between
quality failures and evaluation-infrastructure failures.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Pydantic 2, Langfuse Python SDK `>=4.9.1,<5`, OpenTelemetry, LangGraph,
SQLAlchemy, PyYAML, GitHub Actions

**Storage**: Repository YAML for datasets/gates/score contracts; JSON and Markdown run artifacts;
Langfuse datasets, dataset runs, traces, score configs, and scores; PostgreSQL for live agent data
and durable research sessions

**Testing**: pytest, strict mypy, Ruff; fake Langfuse boundary for unit/contract tests; manual live
workflow validation against the Testing environment

**Target Platform**: Linux GitHub Actions runner and local macOS/Linux development using the Docker
PostgreSQL dev stack

**Project Type**: Python CLI and backend service with a manual GitHub Actions workflow

**Performance Goals**: Complete all repository/Langfuse preflight checks before provider calls;
support 18-25 selected cases; default to one case at a time; preserve existing per-case latency,
tool, retry, token, and cost budgets from `eval-full.v1.yaml`

**Constraints**: Repository data is authoritative; no LLM-as-judge; no automatic required PR gate;
no raw provider prompts/payloads, retrieved passages, hidden reasoning, invalid drafts, credentials,
or exception internals in reports/comments; incomplete infrastructure runs cannot emit a quality
pass/fail verdict

**Scale/Scope**: Two initial repository datasets, eight categories, 18-25 total cases, one Langfuse
dataset run per selected dataset, and one umbrella evaluation execution per manual invocation

## Constitution Check

*GATE: PASS before Phase 0 research. Re-checked after Phase 1 design.*

- **Evidence-first answers: PASS.** Citation-required cases consume the agent's bounded evidence
  validation result. Missing answers or evidence are represented explicitly rather than replaced by
  model-memory judgments.
- **Deterministic data paths: PASS.** Existing route, tool, company, metric, operation, follow-up,
  citation, and operational checks remain deterministic. LLM-as-judge is excluded.
- **Source lineage and citation safety: PASS.** Evaluation observes `AnswerValidation` reason codes
  and lineage checks without exporting raw evidence passages or invalid drafts.
- **Durable research sessions: PASS.** Live cases continue through isolated PostgreSQL-backed
  sessions. The workflow runs migrations and research setup before agent execution.
- **Observable, tested delivery: PASS.** Langfuse datasets/runs/scores use typed contracts and exact
  version metadata. Reports expose sanitized failure codes, and focused tests cover adapters,
  orchestration, failure states, privacy, and CLI behavior.

## Project Structure

### Documentation (this feature)

```text
specs/003-langfuse-evaluation-foundation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── evaluation-cli.md
│   ├── langfuse-mapping.md
│   ├── manual-workflow.md
│   ├── evaluation-execution.schema.json
│   └── score-contract.schema.json
└── tasks.md
```

### Source Code (repository root)

```text
evals/
├── datasets/golden/
│   ├── core.v1.yaml
│   ├── follow_up.v1.yaml
│   └── README.md
├── gates/
│   ├── eval-fast.v1.yaml
│   └── eval-full.v1.yaml
└── score-contracts/
    └── foundation.v1.yaml

src/company_lens/evals/
├── __init__.py
├── golden.py                 # dataset loading, validation, coverage summary
├── models.py                 # observed, report, execution, manifest models
├── agent_runner.py           # isolated case/session execution and exception capture
├── observation.py            # privacy-safe AgentState projection
├── checks.py                 # deterministic item and aggregate evaluation
├── gates.py                  # evaluation-gate loading and threshold application
├── reporting.py              # JSON/Markdown/PR-safe summaries
├── langfuse_sync.py          # dataset and score-config synchronization
├── langfuse_experiment.py    # pinned experiment and score publication adapter
├── orchestrator.py           # multi-dataset preflight/run/finalize state machine
├── cli.py                    # evaluation parser registration and handlers
└── deterministic.py          # compatibility facade for existing imports

.github/workflows/
└── eval-full.yml             # manual Langfuse evaluation and optional PR report

tests/
├── test_golden_dataset.py
├── test_golden_agent_runner.py
├── test_deterministic_evals.py
├── test_langfuse_eval_sync.py
├── test_langfuse_experiment.py
├── test_evaluation_orchestrator.py
├── test_evaluation_reporting.py
└── test_evaluation_cli.py
```

**Structure Decision**: Keep evaluation logic under the existing `company_lens.evals` boundary and
repository contracts under `evals/`. Split the current 958-line deterministic module, 331-line
runner, and evaluation portions of the 1,163-line CLI before adding behavior. `deterministic.py`
remains a narrow re-export facade so existing internal imports can migrate without one large change.
No database migration or frontend change is required.

## Implementation Design

### 1. Repository Contracts

- Extend each golden case with effective `citation_mode` (`required` by default or
  `not_applicable`) and optional `citation_scenario` used only for coverage auditing.
- Add seven reviewed core cases so every existing category has at least two cases while the four
  existing follow-up cases remain unchanged, producing 18 total cases.
- Add `evals/score-contracts/foundation.v1.yaml`. Every entry defines canonical name, item/run
  scope, Langfuse data type, bounds/categories, applicability, aggregation, and evaluator version.
- Rename internal gate types/functions from regression terminology to evaluation-gate terminology;
  preserve the existing gate YAML shape and metrics.

### 2. Dataset and Score-Config Preflight

- Validate all selected repository datasets and the score contract before initializing the live
  research agent or making provider calls.
- Map one repository dataset name to one Langfuse dataset name. Map each case to a project-unique
  UUIDv5 derived from `company-lens:<dataset-name>:<case-id>`.
- Canonicalize each synchronized item payload and store its SHA-256 content hash in metadata.
- Upsert repository-present items as active and archive stale remote items so they remain in
  history but cannot enter future experiments.
- Record the latest synchronization timestamp, refetch that exact version with
  `get_dataset(name, version=timestamp)`, and verify IDs, counts, and hashes before any case runs.
- Reconcile Langfuse score configs from the repository contract. Missing configs are created;
  incompatible existing configs fail preflight. Incompatible semantic changes require a new
  canonical score name.

### 3. Case Execution and Citation Projection

- Run each dataset through its pinned `DatasetClient.run_experiment` with `max_concurrency=1` by
  default. Each case uses one isolated session; all turns in a follow-up case share that session.
- Catch provider/runner exceptions inside the task boundary and return sanitized typed
  infrastructure outcomes. This prevents the SDK from dropping item results or recording raw
  exception text as experiment output.
- Project `AgentState` to a privacy-safe observed result containing routing/tool/operation signals,
  operational metrics, answer presence, citation-validation status/counts/reason codes, and no raw
  final answer or evidence passage.
- For citation-required cases, a captured missing answer is a behavior failure; an answer with no
  trustworthy validation result is an infrastructure failure. Not-applicable cases emit no
  citation-validity score and are excluded from its denominator.

### 4. Deterministic Evaluation and Langfuse Scores

- Expose a pure per-case evaluator reused by local JSON evaluation and Langfuse item evaluators.
- Return BOOLEAN item scores for applicable checks and sanitized comments containing stable reason
  codes only. Pass the reconciled Langfuse score-config ID on every score.
- After the SDK returns, verify selected/result counts, dataset-run linkage, trace IDs, and required
  item scores. Do not trust the SDK's error isolation as completion evidence.
- Only after a complete trusted dataset run, compute and publish NUMERIC aggregate/category scores
  and a CATEGORICAL `gate_status` score. Use deterministic score IDs for idempotent retries.
- On an infrastructure failure, publish `gate_status=not_evaluated` when a dataset-run ID exists,
  preserve partial item records, and suppress aggregate quality scores that could be misleading.

### 5. Multi-Dataset Orchestration and Artifacts

- Preflight every selected dataset first; if any preflight fails, run zero provider-backed cases.
- Create one execution ID and immutable manifest shared by all dataset-specific runs. The manifest
  records code, dataset snapshots/hashes, gate, score contract/config IDs, model/configuration,
  prompt/parser/index versions, execution policy, environment, and workflow metadata.
- Execute pinned datasets sequentially. A quality failure does not stop later datasets; an
  infrastructure failure marks the umbrella execution partial and leaves its gate not evaluated.
- Write `evaluation-execution.json` and `evaluation-summary.md` atomically. Exit `0` for passed,
  `1` for evaluated quality failure, and `2` for infrastructure/not-evaluated failure.

### 6. Manual GitHub Workflow and PR Summary

- Retain `workflow_dispatch`, replace free-form dataset paths with a constrained
  `dataset_scope` choice (`all`, `core`, `follow_up`), and add optional numeric `pr_number`.
- Require Langfuse and provider credentials from the Testing environment. Continue to run
  migrations and initialize PostgreSQL-backed research persistence.
- Run the orchestrator while capturing its exit code, upload artifacts unconditionally, optionally
  create/update one comment identified by a stable HTML marker, then reproduce the captured exit
  code in the final step.
- The comment contains execution/gate status, SHA/ref, dataset counts, aggregate scores, sanitized
  failed-case reasons, artifact URL, and Langfuse run URLs. It never includes raw prompts, answers,
  passages, payloads, or exception text.
- Before commenting, verify that the PR belongs to the current repository and its head SHA equals
  the evaluated commit. A mismatch is a reporting infrastructure failure, never a valid summary.
- Keep this workflow out of required branch-protection checks for feature 003.

## Testing Strategy

- Dataset tests: citation defaults/enums, category minimums, citation-scenario matrix, deterministic
  IDs/hashes, duplicate/unknown fields, and 18-25 total count.
- Deterministic tests: citation applicability/denominators, behavior vs infrastructure outcomes,
  gate `passed|failed|not_evaluated`, score applicability, and privacy-safe reason output.
- Langfuse adapter tests: create/upsert/archive, exact-version refetch, mismatch fail-closed,
  score-config compatibility, deterministic score IDs, complete-run publication, partial-run
  suppression, and flush behavior using fakes at the adapter boundary.
- Orchestrator tests: all preflights precede agent calls, one run per dataset, shared execution ID,
  completed/partial/errored transitions, exit codes, and artifact preservation.
- Workflow/report tests: stable PR marker, one canonical comment, links and required fields,
  permission/reporting failure isolation, and forbidden-content scans.
- Existing agent runner, deterministic evaluator, observability-security, and CLI tests remain green;
  `make check` is the commit gate.

## Post-Design Constitution Re-check

*GATE: PASS.* The design keeps factual evaluation deterministic, preserves citation lineage through
typed validation summaries, uses PostgreSQL-backed live sessions, avoids public sensitive content,
and adds focused contract/unit/integration coverage. No constitution exception is required.

## Complexity Tracking

No constitution violations require justification. The added modules split existing oversized
evaluation/CLI responsibilities along stable contracts rather than introducing a new service or
storage system.
