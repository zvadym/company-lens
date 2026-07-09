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
| `expected` | ExpectedBehavior | Existing company/metric/operation/route/tool/follow-up contract |
| `citation_mode` | `required` or `not_applicable` | Defaults to `required` when omitted |
| `citation_scenario` | enum/null | `valid`, `missing_attempt`, `unknown_evidence_attempt`, or `semantic_mismatch_attempt` |
| `notes` | string/null | Reviewed author note; no secrets or provider payloads |

Validation invariants:

- `not_applicable` is allowed only when the expected answer has no material source-derived claim.
- `citation_scenario` is coverage metadata, not an expected failure. Citation-required cases still
  expect a valid final answer.
- Across the selected foundation datasets, every category has at least two cases, all four citation
  scenarios occur, and the total is between 18 and 25.

## Synchronization Models

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
| `applicability` | enum | `always`, `citation_required`, `follow_up`, `required_tools`, or `prohibited_tools` |
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
- dataset source paths/versions/hashes and exact Langfuse snapshots/item IDs;
- gate name/version/hash and score contract version/hash/config bindings;
- model names and reasoning settings;
- prompt names/sources/versions/content hashes when used;
- parser, embedding, and retrieval-index versions;
- execution policy and per-dataset case selection;
- workflow run URL/actor when available.

It contains no credentials, raw prompts, answers, provider payloads, passages, or exception text.

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
| `artifact_paths` | object | JSON and Markdown relative paths |

Umbrella rules:

- All preflights succeed before any run starts.
- All child runs completed and passed -> execution completed/passed.
- All child runs completed and at least one failed -> execution completed/failed.
- Any infrastructure failure after some work -> execution partial/not_evaluated.
- Preflight failure before trusted case work -> execution errored/not_evaluated.

## Reporting Model

### PREvaluationSummary

Derived from EvaluationExecution; never authoritative.

Required fields: execution/gate status, commit/ref, selected datasets and case counts, aggregate
scores for trusted runs, failed case IDs and reason codes, artifact URL, Langfuse run URLs, and a
stable hidden marker used to update one canonical comment. It excludes all forbidden raw content.
