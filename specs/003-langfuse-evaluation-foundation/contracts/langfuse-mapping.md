# Contract: Repository to Langfuse Mapping

## Project Identity Preflight

`COMPANY_LENS_LANGFUSE_PROJECT_ID` is required for every synchronization, normal evaluation, and
replay. Before any dataset read/write, score-config mutation, or provider-backed case call, use the
configured project-scoped credentials with Langfuse's public `GET /api/public/projects` endpoint and
require the returned project ID to equal the configured value. Project name is diagnostic only.

Missing expected ID, invalid credentials, unavailable identity, organization-scoped credentials, or
an ID mismatch fails closed. The sanitized report may include expected/resolved IDs but never API
keys or raw authorization errors.

## Dataset Mapping

One GoldenDataset maps to one Langfuse dataset with the same `name`.

| Repository field | Langfuse field |
|---|---|
| `dataset.name` | Dataset `name` |
| `dataset.description` | Dataset `description` |
| dataset version/hash/source | Dataset metadata |
| case conversation | DatasetItem `input.conversation` |
| expected behavior | DatasetItem `expectedOutput.behavior` |
| citation mode/scenario | DatasetItem `expectedOutput.citation` |
| reviewed notes | DatasetItem `expectedOutput.notes` |
| category/case/source/version/hash | DatasetItem metadata |

Dataset item ID:

```text
UUIDv5(NAMESPACE_URL, "company-lens:<dataset-name>:<case-id>")
```

Canonical item metadata keys:

```text
schema_version
source = "repository"
source_path
dataset_name
dataset_version
case_id
category
content_hash
```

All active items are upserted even when unchanged so the final synchronization timestamp is a safe
snapshot boundary. Remote items in the mapped dataset whose deterministic IDs are absent locally
are updated to `ARCHIVED`.

## Snapshot Verification

After all upserts/archives:

1. Set the candidate snapshot timestamp to the latest successful item mutation timestamp.
2. Fetch `get_dataset(name, version=<timestamp>)`.
3. Compare the active deterministic ID set with the repository-present ID set.
4. Compare every remote `metadata.content_hash` with the canonical local hash.
5. Reject duplicate IDs, missing metadata, extra active IDs, count mismatch, or hash mismatch.
6. Store the timestamp, IDs, hashes, and archived stale IDs in the manifest.

No selected dataset may begin a provider-backed task until every selected snapshot passes.

For manifest replay, skip all upsert/archive and score-config reconciliation steps. Fetch each
recorded `version_timestamp`, require the recorded project/dataset IDs and active IDs/hashes to match,
and fail before provider calls on any mismatch.

## Experiment Mapping

| CompanyLens object | Langfuse object |
|---|---|
| DatasetEvaluationRun | DatasetRun/experiment run |
| Case execution | Experiment item trace |
| Applicable deterministic check | BOOLEAN trace/observation score |
| Aggregate/category rate | NUMERIC DatasetRun score |
| Evaluation gate status | CATEGORICAL DatasetRun score |
| Evaluation execution ID | DatasetRun and trace metadata |
| Evaluation manifest fingerprint | DatasetRun and trace metadata |

Run names are unique and readable:

```text
company-lens-<dataset-slug>-<short-sha>-<execution-id-prefix>
```

## Foundation Score Names

### Item Scores

| Name | Type | Applicability |
|---|---|---|
| `case_pass` | BOOLEAN | Always for observed behavior |
| `company_pass` | BOOLEAN | Always |
| `metric_pass` | BOOLEAN | Always |
| `operation_pass` | BOOLEAN | Always |
| `route_pass` | BOOLEAN | Always |
| `required_tools_pass` | BOOLEAN | Cases with required tools |
| `prohibited_tools_pass` | BOOLEAN | Cases with prohibited tools |
| `follow_up_safety_pass` | BOOLEAN | Follow-up cases |
| `citation_valid` | BOOLEAN | Citation-required cases |
| `operational_budget_pass` | BOOLEAN | Cases with trustworthy operational metrics |

### Dataset-Run Scores

| Name | Type |
|---|---|
| `case_pass_rate` | NUMERIC 0..1 |
| `company_accuracy` | NUMERIC 0..1 |
| `metric_accuracy` | NUMERIC 0..1 |
| `operation_accuracy` | NUMERIC 0..1 |
| `route_accuracy` | NUMERIC 0..1 |
| `required_tool_recall` | NUMERIC 0..1 |
| `prohibited_tool_pass_rate` | NUMERIC 0..1 |
| `follow_up_safety_accuracy` | NUMERIC 0..1 |
| `citation_validity_pass_rate` | NUMERIC 0..1 |
| `operational_metrics_presence_rate` | NUMERIC 0..1 |
| `operational_budget_pass_rate` | NUMERIC 0..1 |
| `missing_result_rate` | NUMERIC 0..1 |
| `category_document_retrieval` | NUMERIC 0..1 |
| `category_structured_financial` | NUMERIC 0..1 |
| `category_hybrid` | NUMERIC 0..1 |
| `category_cross_document` | NUMERIC 0..1 |
| `category_ambiguous_entity` | NUMERIC 0..1 |
| `category_missing_or_abstain` | NUMERIC 0..1 |
| `category_adversarial` | NUMERIC 0..1 |
| `category_follow_up` | NUMERIC 0..1 |
| `gate_status` | CATEGORICAL: passed, failed, not_evaluated |

All names fit Langfuse's 35-character score-config limit. Run scores are published only after
post-run completeness verification, except `gate_status=not_evaluated` on a partial linked run.

## Idempotency

- Dataset items use deterministic UUIDv5 IDs.
- Dataset-run names include the unique execution ID; rerunning the same execution ID is rejected
  locally. Manifest replay always creates a new execution ID and records the source execution ID and
  manifest fingerprint.
- Scores use UUIDv5 IDs from `<dataset-run-id>:<scope>:<score-name>[:<case-id>]`.
- Every score write sends the full immutable payload and associated score-config ID.

## Privacy

Experiment task output is the CaseObservation contract. It excludes raw final answers, raw evidence,
provider payloads, hidden reasoning, credentials, stack traces, and exception text. Score comments
contain only allowlisted reason codes and short fixed descriptions.
