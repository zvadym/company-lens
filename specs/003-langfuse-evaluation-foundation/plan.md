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
quality failures and evaluation-infrastructure failures. It also adds fail-closed Langfuse project
identity, manifest-driven replay, and an atomic recovery journal for interruption-safe artifacts.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Pydantic 2, Langfuse Python SDK `>=4.9.1,<5`, OpenTelemetry, LangGraph,
SQLAlchemy, PyYAML, GitHub Actions

**Storage**: Repository YAML for datasets/gates/score contracts; JSON recovery journal plus JSON and
Markdown run artifacts; Langfuse datasets, dataset runs, traces, score configs, and scores;
PostgreSQL for live agent data and durable research sessions

**Testing**: pytest, strict mypy, Ruff; fake Langfuse boundary for unit/contract tests; manual live
workflow validation against the Testing environment

**Target Platform**: Linux GitHub Actions runner and local macOS/Linux development using the Docker
PostgreSQL dev stack

**Project Type**: Python CLI and backend service with a manual GitHub Actions workflow

**Performance Goals**: Complete all repository/Langfuse preflight checks before provider calls;
support 18-25 selected cases; default to one case at a time; preserve existing per-case latency,
tool, retry, token, and cost budgets from `eval-full.v1.yaml`; financial-only follow-ups perform no
SEC document processing or embedding calls and do not repeat model-based company extraction after
preparation

**Constraints**: Repository data is authoritative; no LLM-as-judge; no automatic required PR gate;
no raw provider prompts/payloads, retrieved passages, hidden reasoning, invalid drafts, credentials,
or exception internals in reports/comments; incomplete infrastructure runs cannot emit a quality
pass/fail verdict; every Langfuse dataset/score operation and provider call requires verified
expected project identity; replay never mutates synchronized datasets

**Scale/Scope**: Two initial repository datasets, eight categories, 18-25 total cases, one Langfuse
dataset run per selected dataset, and one umbrella evaluation execution per manual invocation

## Constitution Check

*GATE: PASS before Phase 0 research. Re-checked after Phase 1 design.*

- **Evidence-first answers: PASS.** Citation-required cases consume the agent's bounded evidence
  validation result. Missing answers or evidence are represented explicitly rather than replaced by
  model-memory judgments.
- **Deterministic data paths: PASS.** Existing route, tool, company, metric, operation, follow-up,
  citation, and operational checks remain deterministic. Follow-up inherit/replace/extend behavior
  and preparation scope are derived from typed state plus explicit capabilities rather than model
  reason codes alone. LLM-as-judge is excluded.
- **Source lineage and citation safety: PASS.** Evaluation observes `AnswerValidation` reason codes
  and lineage checks without exporting raw evidence passages or invalid drafts.
- **Durable research sessions: PASS.** Live cases continue through isolated PostgreSQL-backed
  sessions. The workflow runs migrations and research setup before agent execution, while the
  evaluation recovery journal preserves orchestration state across process interruption.
- **Observable, tested delivery: PASS.** Langfuse datasets/runs/scores use typed contracts and exact
  version metadata. Reports expose sanitized failure codes, and focused tests cover adapters,
  orchestration, failure states, privacy, and CLI behavior.

## Project Structure

### Documentation (this feature)

```text
specs/003-langfuse-evaluation-foundation/
├── follow-up-remediation-design.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── evaluation-cli.md
│   ├── langfuse-mapping.md
│   ├── manual-workflow.md
│   ├── evaluation-execution.schema.json
│   ├── evaluation-journal.schema.json
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
├── models.py                 # observed, report, execution, manifest/journal models
├── agent_runner.py           # isolated case/session execution and exception capture
├── observation.py            # privacy-safe AgentState projection
├── checks.py                 # deterministic item and aggregate evaluation
├── gates.py                  # evaluation-gate loading and threshold application
├── score_contract.py         # repository score-contract loading and hashing
├── reporting.py              # journal and JSON/Markdown rendering
├── langfuse_mapping.py        # canonical item/score IDs and payload hashes
├── langfuse_scores.py         # score-config reconciliation and publication
├── langfuse_sync.py           # project verification and dataset synchronization
├── langfuse_experiment.py    # pinned experiment and score publication adapter
├── github_reporting.py        # typed canonical PR-comment adapter
├── orchestrator.py           # preflight/replay/run/recovery state machine
├── cli.py                    # evaluation parser registration and handlers
└── deterministic.py          # compatibility facade for existing imports

src/company_lens/observability/
├── langfuse_client.py         # typed client ownership and project identity
└── telemetry.py               # instrumentation using shared client lifecycle

src/company_lens/
├── config.py                  # expected Langfuse project setting
└── cli.py                     # top-level evaluation command dispatch/signals

.github/workflows/
└── eval-full.yml             # manual Langfuse evaluation and optional PR report

tests/
├── evals/
│   ├── __init__.py
│   ├── fakes_langfuse.py
│   ├── test_models.py
│   ├── test_score_contract.py
│   ├── test_langfuse_mapping.py
│   ├── test_langfuse_sync.py
│   ├── test_agent_observation.py
│   ├── test_langfuse_experiment.py
│   ├── test_evaluation_orchestrator.py
│   ├── test_evaluation_reporting.py
│   ├── test_github_reporting.py
│   ├── test_evaluation_workflow.py
│   ├── test_run_evaluation_cli.py
│   ├── test_sync_evaluation_cli.py
│   └── test_contract_schemas.py
├── test_agent_cli.py
├── test_config.py
├── test_golden_dataset.py
├── test_golden_agent_runner.py
├── test_deterministic_evals.py
└── test_observability_security.py
```

**Structure Decision**: Keep evaluation logic under the existing `company_lens.evals` boundary and
repository contracts under `evals/`. Split the current 958-line deterministic module, 331-line
runner, and evaluation portions of the 1,163-line CLI before adding behavior. Extract Langfuse client
ownership from the 590-line telemetry module into `observability/langfuse_client.py`, leaving
telemetry focused on instrumentation. `deterministic.py` remains a narrow re-export facade so
existing internal imports can migrate without one large change. No database migration or frontend
change is required.

## Implementation Design

### 1. Repository Contracts

- Extend each golden case with effective `citation_mode` (`required` by default or
  `not_applicable`) and optional `citation_scenario` used only for coverage auditing. The three
  non-valid scenario values are challenge attempts, never expected invalid final answers.
- Add seven reviewed core cases so every existing category has at least two cases, producing 18
  total cases. Clarify the four follow-up prompts with explicit QoQ/YoY operations and require
  operation inheritance so `operation_accuracy` measures a reviewed, unambiguous contract.
- Match reviewed company identities by canonical name or ticker in deterministic follow-up checks
  while preserving independent status and source validation.
- Add `evals/score-contracts/foundation.v1.yaml`. Every entry defines canonical name, item/run
  scope, Langfuse data type, bounds/categories, applicability, and aggregation; the contract-level
  evaluator version applies to every definition.
- Rename internal gate types/functions from regression terminology to evaluation-gate terminology;
  preserve the existing gate YAML shape and metrics.

### 2. Dataset and Score-Config Preflight

- Validate all selected repository datasets and the score contract before initializing the live
  research agent or making provider calls.
- Require `COMPANY_LENS_LANGFUSE_PROJECT_ID`. Resolve the project associated with the configured
  project-scoped key through Langfuse's public project endpoint and compare its ID before any dataset
  read/write or provider call. Missing, unavailable, or mismatched identity fails closed.
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
- If provider infrastructure still fails after per-node retries and the execution policy permits
  retries, replay the complete case once in a fresh isolated session under the same dataset item
  trace. Never replay observed behavior failures; a second provider failure remains infrastructure
  with a not-evaluated gate, and the replay contributes to operational retry metrics.
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
- Freeze explicit project/snapshot/score-config failure markers on preflight failure. With a reporting
  target, transition the errored/not-evaluated execution to `reporting/pending` so a sanitized PR
  summary can explain the infrastructure failure; without a target, transition directly to
  `terminal/not_requested`.
- Create one execution ID and immutable manifest shared by all dataset-specific runs. The manifest
  records code, dataset snapshots/hashes, gate, score contract/config IDs, model/configuration,
  prompt/parser/index versions, execution policy, environment, and workflow metadata.
- For `--manifest` replay, validate the source manifest and all local hashes, fetch each exact remote
  snapshot read-only, reject runtime overrides of immutable inputs, and create a new execution ID
  with `replay_of_execution_id` plus the source manifest fingerprint. Replay performs no sync,
  archive, score-config mutation, or dataset-item mutation.
- Create `evaluation-journal.json` before project/preflight access and atomically replace it after
  every terminal project check, dataset preflight, case, dataset-run, and PR-reporting transition.
  Journal sequence numbers are monotonic, terminal records are append-only by identity, and every
  checkpoint validates before replacing the previous file.
- Initialize journal reporting state and exact target from paired optional `--repository` and
  `--pr-number`: `pending` with `{repository, pr_number}` when supplied and `not_requested` with null
  target otherwise. Evaluation execution never calls GitHub directly.
- Execute pinned datasets sequentially. A quality failure does not stop later datasets; an
  infrastructure failure marks the umbrella execution partial and leaves its gate not evaluated.
- Materialize `evaluation-execution.json` and `evaluation-summary.md` atomically from the latest
  journal. `SIGINT`/`SIGTERM` writes an interruption checkpoint and partial artifacts, then enters
  `reporting/pending` when a target exists or `terminal/not_requested` otherwise; an uncatchable stop
  leaves the last valid journal for `recover-evaluation`. Exit `0` for passed, `1` for evaluated
  quality failure, and `2` for infrastructure/not-evaluated failure.

### 6. Manual GitHub Workflow and PR Summary

- Retain `workflow_dispatch`, replace free-form dataset paths with a constrained
  `dataset_scope` choice (`all`, `core`, `follow_up`), and add optional numeric `pr_number`.
- Require Langfuse credentials, expected Langfuse project ID, and provider credentials from the
  Testing environment. Continue to run migrations and initialize PostgreSQL-backed research
  persistence.
- Run the orchestrator while capturing its exit code, recover missing final artifacts when possible,
  optionally create/update one comment identified by a stable HTML marker, upload the resulting
  reporting-terminal artifacts unconditionally, then reproduce the captured exit code in the final
  step unless recovery/reporting requires infrastructure exit `2`.
- The comment contains execution/gate status, SHA/ref, dataset counts, aggregate scores, sanitized
  failed-case reasons, artifact URL, and Langfuse run URLs. It never includes raw prompts, answers,
  passages, payloads, or exception text.
- Before commenting, verify that the PR belongs to the current repository and its head SHA equals
  the evaluated commit. A mismatch is a reporting infrastructure failure, never a valid summary.
- `report-evaluation-pr` requires the matching recovery journal in reporting/pending state. It
  terminalizes only reporting status and sanitized reporting failure codes; evaluation status,
  gate, manifest, runs, scores, final JSON/Markdown, and Langfuse records remain immutable.
- Keep this workflow out of required branch-protection checks for feature 003.

### 7. Follow-up Correctness and Capability-Aware Preparation

- Introduce `CompanyDataPreparationRequirements` in a focused ingestion module extracted from the
  existing 280-line on-demand preparation implementation. It independently declares whether
  financial facts and/or SEC documents plus embeddings are required.
- Derive requirements from `QuestionAnalysis.required_capabilities`. Calculations and charts do not
  imply document preparation; only the `documents` capability enables SEC filing ingestion,
  document processing, and embedding indexing.
- Make readiness requirement-specific. Existing financial facts satisfy facts-only preparation even
  when no indexed chunks exist; document requests retain the existing chunk/index readiness check.
- Retain the unmerged current-turn query through resolution. Finalize follow-up context at the end
  of `prepare_company_data`, including its no-external-work path, before planning.
- Determine company-set semantics from explicit current companies and deterministic add/include
  markers, with model reason codes as supporting signals: no current company inherits, a current
  company replaces, and add/include extends.
- Build `ResearchFrame.company_targets` with source per target by comparing the pre-merge current
  query with the final merged query. Mixed prior/new sets must preserve mixed provenance.
- Replace post-preparation model re-extraction with deterministic local ticker resolution and merge.
  This preserves local company enrichment while removing duplicate entity-extraction generations.
- Preserve current metrics when explicit and otherwise inherit prior metrics; preserve the current
  plan operation with the existing frame fallback for inherited calculations.

## Testing Strategy

- Dataset tests: citation defaults/enums, category minimums, citation-scenario matrix, deterministic
  IDs/hashes, duplicate/unknown fields, and 18-25 total count.
- Deterministic tests: citation applicability/denominators, behavior vs infrastructure outcomes,
  gate `passed|failed|not_evaluated`, score applicability, and privacy-safe reason output.
- Langfuse adapter tests: project-identity mismatch before writes, create/upsert/archive,
  exact-version refetch, mismatch fail-closed, score-config compatibility, deterministic score IDs,
  complete-run publication, partial-run suppression, and flush behavior using fakes at the adapter
  boundary.
- Orchestrator tests: all preflights precede agent calls, one run per dataset, shared execution ID,
  manifest replay without remote mutation, completed/partial/errored transitions, injected
  interruption boundaries, journal recovery, exit codes, and artifact preservation.
- Workflow/report tests: stable PR marker, one canonical comment, links and required fields,
  exact reporting-target match, reporting success/failure journal terminalization, immutable
  evaluation verdict/artifacts, permission/reporting failure isolation, and forbidden-content scans.
- Existing agent runner, deterministic evaluator, observability-security, and CLI tests remain green;
  `make check` is the commit gate.
- Preparation tests verify facts-only, documents-only, combined, and requirement-specific readiness
  paths and assert that unrequested SEC/processing/embedding services are never invoked.
- Follow-up workflow tests cover inherit, replace, and extend, mixed company provenance, metric and
  operation inheritance, and the absence of post-preparation LLM extraction.
- Live acceptance runs the four follow-up cases first and requires all deterministic, citation, and
  operational checks to pass without threshold changes before the full 18-case workflow runs.

## Post-Design Constitution Re-check

*GATE: PASS.* The design keeps factual evaluation deterministic, preserves citation lineage through
typed validation summaries, uses PostgreSQL-backed live sessions, avoids public sensitive content,
and adds focused contract/unit/integration coverage. Capability-aware preparation strengthens the
constitution's deterministic-data-path requirement by preventing narrative ingestion for
structured-only questions. No constitution exception is required.

## Complexity Tracking

No constitution violations require justification. The added modules split existing oversized
evaluation/CLI responsibilities and extract preparation requirements/readiness from the 280-line
on-demand ingestion module along stable contracts rather than introducing a new service or storage
system.
