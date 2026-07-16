# Data Model: Langfuse Evaluation Foundation

## Golden Dataset Models

### GoldenDataset

Repository-authored source of truth for one Langfuse dataset.

| Field | Type | Rules |
|---|---|---|
| `name` | string | Stable kebab-case name; maps one-to-one to Langfuse dataset name |
| `version` | integer | Positive repository version; metadata, not item identity |
| `description` | string/null | Privacy-safe reviewed description |
| `cases` | GoldenCase[] | Non-empty; case IDs unique within the dataset |
| `source_path` | path | Added by the loader, repository-relative, inside the golden dataset root |
| `content_hash` | SHA-256 | Canonical hash of the complete validated dataset payload |

### GoldenCase

| Field | Type | Rules |
|---|---|---|
| `id` | string | Existing stable snake-case pattern ending in a three-digit suffix |
| `category` | enum | One of the eight existing golden categories |
| `conversation` | ConversationTurn[] | Non-empty; follow-up cases contain at least two user turns |
| `expected` | ExpectedBehavior | Company/metric/operation/route/tool/follow-up contract; inherited operations must be explicit and reviewed |
| `citation_mode` | `required` or `not_applicable` | Defaults to `required` when omitted |
| `citation_scenario` | enum/null | `valid`, `missing_attempt`, `unknown_evidence_attempt`, or `semantic_mismatch_attempt`; the latter three are challenge attempts |
| `notes` | string/null | Reviewed author note; no secrets or provider payloads |

Validation invariants:

- `not_applicable` is allowed only when the expected answer has no material source-derived claim.
- `citation_scenario` is coverage metadata, not an expected failure. Citation-required cases still
  expect a valid final answer.
- Across the selected foundation datasets, every category has at least two cases, all four citation
  scenarios occur, and the total is between 18 and 25.

## Synchronization Models

### LangfuseProjectIdentity

Verified before any Langfuse dataset read/write, score-config mutation, or provider-backed case call.

| Field | Type | Rules |
|---|---|---|
| `expected_project_id` | string/null | Required configuration; null is an explicit missing marker in failed preflight artifacts |
| `resolved_project_id` | string/null | Returned by Langfuse's public project endpoint; null when identity is unavailable |
| `resolved_project_name` | string/null | Privacy-safe diagnostic metadata only; ID remains authoritative |
| `checked_at` | UTC datetime | Records the completed lookup attempt even when unavailable |
| `status` | enum | `verified`, `mismatched`, or `unavailable` |

The check passes only when both IDs are equal. Missing configuration, authentication failure,
unavailable identity, or mismatch is an infrastructure failure before remote mutation.

### SynchronizedDatasetItem

Canonical Langfuse representation of a GoldenCase.

| Field | Type | Rules |
|---|---|---|
| `id` | UUID string | UUIDv5 of `company-lens:<dataset-name>:<case-id>` |
| `dataset_name` | string | Equal to GoldenDataset.name |
| `input` | object | Contains only the reviewed conversation turns |
| `expected_output` | object | Expected behavior, citation mode/scenario, and reviewed notes |
| `metadata` | object | Schema version, source path, dataset name/version, case ID, category, content hash |
| `status` | `ACTIVE` or `ARCHIVED` | Repository-present items active; stale items archived |
| `content_hash` | SHA-256 | Hash of canonical input, expected output, and authoritative metadata |

Identity invariants:

- Dataset version and content hash do not change the item ID.
- Moving a case to another dataset or renaming the case creates a new item identity; the old item is
  archived as stale.
- A successful sync readback contains exactly the expected active IDs and hashes.

### DatasetSnapshot

| Field | Type | Rules |
|---|---|---|
| `dataset_name` | string | Repository/Langfuse shared name |
| `repository_version` | integer | GoldenDataset.version |
| `repository_hash` | SHA-256 | Full validated dataset hash |
| `langfuse_dataset_id` | string | Remote dataset ID |
| `langfuse_project_id` | string | Equal to the verified expected/resolved project ID |
| `version_timestamp` | UTC datetime | Exact item-version timestamp passed to `get_dataset` |
| `active_item_ids` | string[] | Sorted and unique |
| `active_item_hashes` | map | Item ID to content hash |
| `stale_item_ids` | string[] | Archived during this sync; sorted and unique |

The snapshot is valid only after exact-version readback matches all repository-present IDs and
hashes. All selected snapshots must validate before live agent construction.

## Score Contract Models

### ScoreContract

| Field | Type | Rules |
|---|---|---|
| `name` | string | `company-lens-foundation` |
| `version` | integer | Positive repository contract version |
| `evaluator_version` | string | Stable evaluator implementation identifier |
| `scores` | ScoreDefinition[] | Canonical score names unique across the contract |
| `content_hash` | SHA-256 | Canonical contract hash stored in the run manifest |

### ScoreDefinition

| Field | Type | Rules |
|---|---|---|
| `name` | string | Langfuse-compatible, at most 35 characters |
| `scope` | `item` or `run` | Determines trace/observation vs dataset-run attachment |
| `data_type` | `BOOLEAN`, `NUMERIC`, or `CATEGORICAL` | `TEXT` is not used for foundation quality metrics |
| `minimum` / `maximum` | number/null | Required for numeric rates: 0.0 to 1.0 |
| `categories` | string[] | Required for categorical `gate_status` |
| `applicability` | enum | `always`, `citation_required`, `follow_up`, `required_tools`, `prohibited_tools`, or `operational_metrics` |
| `aggregation` | string/null | Run metric/check source; absent for item-only scores |
| `description` | string | Stable semantic definition |

### ScoreConfigBinding

| Field | Type | Rules |
|---|---|---|
| `score_name` | string | References ScoreDefinition.name |
| `langfuse_config_id` | string | Existing compatible or newly created immutable config |
| `compatible` | boolean | Must be true before provider calls |

An existing config with the same name but incompatible type/range/categories is an infrastructure
error. Semantic changes require a new canonical score name.

The manifest records score-config preflight status as `verified` or `failed`. `verified` requires one
binding for every applicable score definition; `failed` uses an empty binding list as the explicit
unavailable marker and cannot be replayed.

## Observation and Evaluation Models

### CitationObservation

Privacy-safe projection of the agent's AnswerValidation.

| Field | Type | Rules |
|---|---|---|
| `mode` | citation mode | Copied from GoldenCase |
| `answer_present` | boolean | No answer text is stored |
| `validation_present` | boolean | True only when a trustworthy AnswerValidation exists |
| `valid` | boolean/null | Null for not-applicable or infrastructure-unavailable validation |
| `claim_count` | integer | Non-negative |
| `cited_evidence_count` | integer | Non-negative |
| `unknown_evidence_ids` | string[] | IDs only, no evidence content |
| `reason_codes` | string[] | Sorted, unique, allowlisted validator codes |

### CaseObservation

Extends the current observed result with terminal and citation state.

| Field | Type | Rules |
|---|---|---|
| `case_id` | string | Matches exactly one selected GoldenCase |
| `outcome` | `observed` or `infrastructure_error` | Infrastructure outcome never becomes quality failure |
| `failure_code` | string/null | Sanitized allowlisted code; no raw exception text |
| `companies`, `metrics`, `operation`, `route`, `tools` | existing types | Privacy-safe deterministic behavior signals |
| `trajectory` | event[] | Node/status/duration only |
| `operational` | metrics/null | Existing bounded latency/tool/retry/token/cost values |
| `citation` | CitationObservation | Required for every selected case |

Captured missing answer or agent terminal failure remains `outcome=observed`; its deterministic
checks fail. Provider/runner/evaluator malfunction uses `outcome=infrastructure_error`.
`operational.retry_count` includes both per-node retries and the single permitted whole-case replay.
The replay uses a fresh session but remains part of the same case observation and Langfuse dataset
item trace. `operational.case_attempts` is a positive privacy-safe count that distinguishes a normal
single attempt from the permitted replay. Aggregate model API calls are checked against the
repository-authored per-attempt ceiling multiplied by this count; aggregate latency, token, and cost
budgets remain unchanged so replay overhead stays visible.

### CaseEvaluation

| Field | Type | Rules |
|---|---|---|
| `case_id` / `category` | string | Copied from selected case |
| `passed` | boolean/null | Null for infrastructure error |
| `checks` | map of boolean | Only applicable deterministic checks |
| `failure_codes` | string[] | Stable privacy-safe codes |
| `scores` | map | One value per applicable item score definition |

## Run and Execution Models

### DatasetEvaluationRun

| Field | Type | Rules |
|---|---|---|
| `dataset_name` / `dataset_version` | string/integer | Repository identity |
| `snapshot` | DatasetSnapshot | Exact verified Langfuse input |
| `status` | `completed`, `partial`, or `errored` | Independent of quality gate |
| `gate_status` | `passed`, `failed`, or `not_evaluated` | Pass/fail only when completed and trustworthy |
| `selected_case_ids` | string[] | Ordered, unique, subject to per-dataset max |
| `case_results` | CaseEvaluation[] | One terminal record per selected case on completed runs |
| `aggregate_scores` | map | Present only for trusted completed runs |
| `langfuse_dataset_run_id` | string/null | Required when any experiment item linked successfully |
| `langfuse_run_url` | URL/null | Safe UI link |

State transitions:

```text
preflighted -> completed
preflighted -> partial       (some item/run records exist, infrastructure failed)
preflighted -> errored       (no trusted item result)

completed -> gate passed | gate failed
partial/errored -> gate not_evaluated
```

### EvaluationRunManifest

Immutable execution fingerprint containing:

- execution ID, commit SHA, source ref, environment, service version;
- optional `replay_of_execution_id` and required source manifest fingerprint for replay executions;
- verified expected/resolved Langfuse project ID and verification timestamp;
- dataset source paths/versions/hashes/selected case IDs plus preflight state and exact Langfuse
  snapshots/item IDs or explicit unavailable markers;
- gate name/version/hash and score contract version/hash/config bindings;
- model names and reasoning settings;
- prompt names/sources/versions/content hashes when used;
- parser, embedding, and retrieval-index versions;
- execution policy and per-dataset case selection;
- workflow run URL/actor when available.

It contains no credentials, raw prompts, answers, provider payloads, passages, or exception text.

Manifest invariants:

- `manifest_fingerprint` is the SHA-256 of canonical manifest content excluding the fingerprint field.
- A normal execution synchronizes and pins snapshots before freezing the manifest.
- If preflight fails, the manifest still freezes all local inputs and explicit project/snapshot/config
  unavailable states; it is stored locally but cannot be used for replay.
- A replay validates local hashes and reads the exact recorded snapshots without any dataset,
  dataset-item, stale-item, or score-config mutation.
- Replay creates a new `execution_id`; `replay_of_execution_id` identifies the source execution, and
  immutable manifest fields cannot be overridden from the CLI.
- Replay is allowed only when project identity is `verified`, every dataset preflight state is
  `verified`, every exact snapshot is present, and all required score-config bindings are present.

### EvaluationRecoveryJournal

Atomically replaced orchestration checkpoint used before final artifacts exist and after
interruption.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | Starts at 1 |
| `execution_id` | UUID string | Matches the active execution |
| `sequence` | integer | Starts at 0 and increases by exactly one per replacement |
| `updated_at` | UTC datetime | Monotonic checkpoint timestamp |
| `manifest` | EvaluationRunManifest/null | Null only before normal preflight has frozen a manifest |
| `project_identity` | LangfuseProjectIdentity/null | Null only before the project lookup completes |
| `phase` | enum | `initialized`, `project_verified`, `preflighted`, `running`, `reporting`, or `terminal` |
| `status` | enum | `running`, `completed`, `partial`, or `errored` |
| `gate_status` | enum | `pending`, `passed`, `failed`, or `not_evaluated` |
| `reporting_status` | enum | `not_requested`, `pending`, `succeeded`, or `failed`; independent of evaluation status/gate |
| `reporting_target` | ReportingTarget/null | Exact `{repository, pr_number}` when reporting is requested; otherwise null |
| `dataset_runs` | DatasetEvaluationRun[] | At most one current record per selected dataset |
| `terminal_cases` | CaseIdentity[] | Unique `{dataset_name, case_id}` identities with terminal observations |
| `failure_codes` | string[] | Sanitized allowlisted reasons only |
| `reporting_failure_codes` | string[] | Sanitized reporting-only reasons; empty unless reporting failed |

Allowed state matrix:

| Phase | Evaluation status | Gate status | Reporting status |
|---|---|---|---|
| `initialized` | `running` | `pending` | `not_requested` or `pending` |
| `project_verified` | `running` | `pending` | `not_requested` or `pending` |
| `preflighted` | `running` | `pending` | `not_requested` or `pending` |
| `running` | `running` | `pending` | `not_requested` or `pending` |
| `reporting` | `completed`, `partial`, or `errored` | derived from evaluation status | `pending` |
| `terminal` | `completed`, `partial`, or `errored` | derived from evaluation status | `not_requested`, `succeeded`, or `failed` |

`completed` evaluation status permits gate `passed|failed`; `partial|errored` requires
`not_evaluated`. A workflow with a PR target stores the exact repository/PR pair, starts with
reporting `pending`, and must finish `succeeded|failed`; a run without a PR target remains
`not_requested` with a null target.

`project_verified`, `preflighted`, and `running` require verified project identity. `preflighted` and
`running` additionally require verified snapshots for every selected dataset and verified
score-config bindings. `reporting` requires a frozen manifest but explicitly permits failed project,
snapshot, or score-config markers so the PR can safely explain why the gate was not evaluated. Any
preflight failure transitions to `reporting/pending` when a reporting target exists, or directly to
`terminal/not_requested` otherwise; provider-backed case execution remains forbidden.

Journal invariants:

- Write a complete candidate to a sibling temporary file, validate it, `fsync`, and atomically
  replace `evaluation-journal.json`; never edit the active file in place.
- Existing terminal case and dataset-run records cannot disappear or change identity in a later
  sequence; only defined state transitions may enrich them.
- Case identity is always the structured pair `{dataset_name, case_id}`; a bare case ID is never a
  journal identity because uniqueness is guaranteed only within one dataset.
- `SIGINT` and `SIGTERM` append a sanitized interruption failure code, set evaluation
  `partial|errored` plus `not_evaluated`, checkpoint, and materialize partial artifacts. The journal
  then enters `reporting/pending` when a reporting target exists, or `terminal/not_requested` when it
  does not.
- PR reporting may update only `sequence`, `updated_at`, `phase`, `reporting_status`, and
  `reporting_failure_codes`. It cannot change evaluation status/gate, manifest, dataset runs, case
  identities, scores, or already materialized execution JSON.
- `recover-evaluation` validates the last journal, advances interrupted evaluation state to
  `partial|errored` plus `not_evaluated`, chooses `reporting/pending` or `terminal/not_requested`
  from the stored target, and materializes partial artifacts without provider calls or Langfuse
  mutation. A truncated temporary file is ignored; an invalid active journal fails closed and is
  never presented as trustworthy output.

### EvaluationExecution

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | Starts at 1 |
| `execution_id` | UUID string | Shared across all dataset runs and artifacts |
| `started_at` / `completed_at` | UTC datetime | Both required in the final artifact; completion is not earlier than start |
| `status` | `completed`, `partial`, or `errored` | Derived from child runs/preflight |
| `gate_status` | `passed`, `failed`, or `not_evaluated` | Umbrella result |
| `manifest` | EvaluationRunManifest | Immutable after provider execution begins |
| `runs` | DatasetEvaluationRun[] | One per selected repository dataset |
| `failure_codes` | string[] | Sanitized execution-level reasons |
| `artifact_paths` | object | Journal, JSON, and Markdown relative paths |

Umbrella rules:

- All preflights succeed before any run starts.
- All child runs completed and passed -> execution completed/passed.
- All child runs completed and at least one failed -> execution completed/failed.
- Any infrastructure failure after some work -> execution partial/not_evaluated.
- Preflight failure before trusted case work -> execution errored/not_evaluated.

## Agent Remediation Models

### CompanyDataPreparationRequirements

Immutable ingestion-owned value used by the agent tool boundary.

| Field | Type | Rules |
|---|---|---|
| `financial_facts` | boolean | Enables company-facts readiness and ingestion |
| `documents` | boolean | Enables SEC filing ingestion, processing, and embedding readiness/indexing |

At least one field must be true for external preparation work. An all-false value is valid at the
workflow boundary and means preparation is skipped while follow-up context is still finalized.

### Follow-up context inputs

Follow-up finalization consumes two `ResolvedQuery` values without persisting a new database model:

| Value | Meaning |
|---|---|
| `current_query` | Companies and constraints resolved from the current user turn before memory merge |
| `merged_query` | Final inherit/replace/extend result used by planning and observation |

`ResearchFrame.company_targets` derives each target's `source` from these inputs. Current companies
remain `current_question` (or the existing prepared-ticker source where applicable); companies found
only in the merged query are `follow_up_context`.

## Calculation Operation Reconciliation Models

These are immutable in-memory agent contracts. They require no database migration. Final session
memory continues to persist the validated `ExecutionPlan`; inherited intents are derived only from
that final plan.

### CalculationIntent

LLM-owned semantic intent emitted by parsing.

| Field | Type | Rules |
|---|---|---|
| `operation` | CalculationOperation | One of the existing supported calculation operations |
| `metrics` | string[] | Canonical typed metric names without company, ticker, or entity qualifiers; empty when unspecified; supports two-input operations |
| `window` | integer/null | Positive and required only for `rolling_average`; null for every other operation |
| `years` | decimal/null | Positive and required only for `cagr`; null for every other operation |
| `base` | decimal/null | Optional explicit base only for `normalised_index`; null for every other operation |

`QuestionAnalysis.calculation_intents` defaults to an empty tuple for repository fixtures.
`QuestionAnalysis.inherit_previous_calculation_intents` defaults to false. Explicit current intents
take precedence over inheritance. A vague compatible follow-up sets inheritance true and derives its
effective intents from `SessionMemory.last_execution_plan` after that plan has been reconciled and
validated.

Source-selection periods such as "last eight quarters" remain in typed source requests and are not
encoded as calculation `window`. That field always means the rolling-average calculation window.
Equivalent multi-company requests use one shared intent for the same operation, metrics, and scalar
parameters. The detector also treats schema-valid duplicate intents as equivalent when their typed
operation contract agrees and each metric ends with the complete canonical source-metric token
sequence; it does not use company dictionaries or inspect user text.

### EffectiveCalculationIntent

Workflow-local projection used for comparison; it is not added to `AgentState` or persistence.

| Field | Type | Rules |
|---|---|---|
| `operation` | CalculationOperation | Copied from explicit intent or final previous plan |
| `metrics` | string[] | Matched against numeric source requests, never free-form text |
| `window`, `years`, `base` | scalar/null | Applicable non-null values are authoritative conflict constraints; inapplicable non-null values are invalid |
| `source` | `current` or `inherited` | Privacy-safe provenance for conflict metadata |

One effective intent may cover multiple company-specific calculation branches with the same source
metrics. Equivalent duplicate intents may cover those branches without creating false ambiguity.
Every effective intent must be represented by at least one compatible branch.

### OperationConflict

Sanitized result of deterministic structured comparison.

| Field | Type | Rules |
|---|---|---|
| `required` | boolean | False only when intents and every calculation branch are compatible |
| `reason_codes` | string[] | Allowlisted categories such as operation, metrics, parameters, inheritance, missing, or ambiguous |
| `branch_ids` | string[] | Existing conflicting calculation branch IDs only |

The detector reads typed intent, branch, source-request, and previous-final-plan fields. It never
reads user text. `required=false` causes zero reconciliation model calls.

### BranchOperationDecision

Structured repair-model decision.

| Field | Type | Rules |
|---|---|---|
| `branch_id` | string | Must identify one existing calculation branch |
| `operation` | CalculationOperation | Final operation for that branch |
| `window` | integer/null | Positive and required only for `rolling_average`; null otherwise |
| `years` | decimal/null | Positive and required only for `cagr`; null otherwise |
| `base` | decimal/null | Valid only for `normalised_index`; null otherwise |

Decision `window` and `years` apply exactly, so null clears an irrelevant prior value. Decision
`base=null` preserves the existing non-null branch base; an applicable non-null decision replaces
it. Any inapplicable non-null scalar makes the reconciliation semantically invalid.

### OperationReconciliation

| Field | Type | Rules |
|---|---|---|
| `branch_operations` | BranchOperationDecision[] | Exactly one decision for every calculation branch |

Application invariants:

- branch count, order, IDs, kinds, dependencies, input references, optional flags, and source/chart
  fields remain byte-for-byte unchanged;
- only `operation`, `window`, `years`, and `base` may change;
- operation arity must remain compatible with unchanged inputs;
- scalar parameters must be applicable to the selected operation;
- every effective intent must be represented after application;
- complete domain plan validation runs before cache hydration or tools;
- provider/response exhaustion preserves provider error categories;
- schema-valid semantic incompatibility emits `operation_reconciliation_failed` as a validation
  behavior failure;
- both failure paths execute zero tools for the affected plan.

State transitions:

```text
planned + consistent -> reconciliation skipped -> validated final plan
planned + conflict -> reconciling -> reconciled -> validated final plan
planned + conflict -> provider failure -> infrastructure/not evaluated
planned + conflict -> semantic invalidity -> observed quality failure
```

## Reporting Model

### PREvaluationSummary

Derived from EvaluationExecution; never authoritative.

Required fields: execution/gate status, commit/ref, selected datasets and case counts, aggregate
scores for trusted runs, failed case IDs and reason codes, artifact URL, Langfuse run URLs, and a
stable hidden marker used to update one canonical comment. It excludes all forbidden raw content.
