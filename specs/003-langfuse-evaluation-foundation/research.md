# Phase 0 Research: Langfuse Evaluation Foundation

## Baseline Finding

The configured Langfuse project currently has zero datasets. CompanyLens already exports live
traces, sessions, prompt metadata, model usage, and privacy-safe OpenTelemetry observations, while
repository golden datasets, the live runner, deterministic checks, and gates already exist locally.
Feature 003 therefore adds the missing dataset-run/score layer rather than replacing tracing.

## Decision 1: Use the Langfuse Python experiment runner directly

**Decision**: Use the installed Langfuse Python SDK experiment runner through pinned
`DatasetClient` instances. Raise the project dependency floor to `langfuse>=4.9.1,<5`.

**Rationale**: The SDK creates dataset runs, traces every item, supports item evaluators, exposes
run URLs, and accepts exact dataset versions through the public `get_dataset(..., version=...)`
and `DatasetClient.run_experiment(...)` APIs in 4.9.1. The current project already uses Langfuse v4
and OpenTelemetry.

**Alternatives considered**:

- Local-data experiments: rejected because Langfuse creates traces but no dataset run.
- Hand-built trace/dataset-run API calls: rejected because they duplicate supported SDK behavior.
- Older SDK minimum: rejected because exact version retrieval is required for reproducibility.

References: [Experiments via SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk),
[Python experiment API](https://python.reference.langfuse.com/langfuse/experiment)

## Decision 2: Do not use `langfuse/experiment-action` as the orchestration owner

**Decision**: Keep the existing manual GitHub workflow and call the project-owned Python
orchestrator. Use a project-owned PR summary step.

**Rationale**: The action's top-level inputs select one dataset and its automatic comment describes
one action execution. Feature 003 requires several independently versioned Langfuse dataset runs,
one shared execution manifest, one canonical PR comment, project-specific exit codes, and artifact
preservation. The SDK remains the supported experiment engine; only orchestration/reporting stays
inside CompanyLens.

**Alternatives considered**:

- One action invocation per dataset: rejected because it creates fragmented comments/results and
  complicates an umbrella gate.
- One merged Langfuse dataset: rejected by the approved one-to-one repository mapping.
- Automatic `pull_request` gate: rejected because this feature is manual and non-required.

Reference: [Experiments in CI/CD](https://langfuse.com/docs/evaluation/experiments/experiments-ci-cd)

## Decision 3: Synchronize active items and archive stale items

**Decision**: Upsert repository-present cases with deterministic UUIDv5 IDs and archive remote items
whose IDs are no longer in the repository dataset.

**Rationale**: Langfuse upserts by item ID, and archived items remain in history while being removed
from future experiment runs. The identity excludes dataset version and content hash, so reviewed
updates create item versions rather than duplicates.

**Alternatives considered**:

- Delete stale items: rejected because archive preserves audit history.
- Leave stale items active and filter locally: rejected because the Langfuse dataset view would not
  represent the reviewed active set and could be run incorrectly outside CompanyLens.
- Include dataset version in item ID: rejected because every version would duplicate cases.

Reference: [Langfuse datasets](https://langfuse.com/docs/evaluation/experiments/datasets)

## Decision 4: Pin and verify the exact synchronized item snapshot

**Decision**: Hash the canonical synchronized payload, capture the final item-update timestamp,
refetch that exact dataset version, and compare active IDs/counts/hashes before provider calls.

**Rationale**: Langfuse versions every item addition, update, archive, and deletion. A timestamp-pinned
dataset prevents later edits from changing the run. Verification protects against partial sync,
concurrent edits, and wrong-project credentials. All selected datasets preflight before the first
agent call.

**Alternatives considered**:

- Run latest immediately after sync: rejected because a concurrent edit can change the evaluated set.
- Trust repository hashes without remote readback: rejected because it does not prove remote state.
- Best-effort mismatch warning: rejected by the fail-closed reproducibility requirement.

Reference: [Dataset item versioning](https://langfuse.com/changelog/2025-12-15-dataset-versioning)

## Decision 5: Treat SDK completion as untrusted until post-run verification

**Decision**: Catch task exceptions inside the CompanyLens task adapter, return sanitized typed
outcomes, and verify result cardinality, linkage, trace IDs, and expected scores after the SDK run.

**Rationale**: Langfuse's experiment runner isolates task failures and omits failed task results;
evaluator failures are logged and can yield missing scores. That behavior is useful generally but
cannot by itself distinguish a quality regression from evaluation-infrastructure failure.

**Alternatives considered**:

- Let task exceptions propagate: rejected because results can disappear and exception text can be
  recorded as experiment output.
- Infer completeness from aggregate scores: rejected because missing items bias denominators.
- Fail on the first case: rejected because partial records must remain inspectable.

## Decision 6: Publish aggregates only after trusted completion

**Decision**: Use SDK item evaluators for deterministic per-item scores. After post-run verification,
compute aggregate/category metrics and the evaluation gate in CompanyLens, then publish dataset-run
scores explicitly with deterministic score IDs.

**Rationale**: Run evaluators receive only successful SDK item results. Deferring aggregate scores
prevents a partial run from looking healthy. A partial run may publish only categorical
`gate_status=not_evaluated` when a dataset-run ID exists.

**Alternatives considered**:

- SDK run evaluators for all aggregates: rejected because omitted items are invisible to them.
- Derive the gate from Langfuse analytics later: rejected because workflow exit status and local
  artifacts need the same deterministic decision immediately.

## Decision 7: Reconcile immutable Langfuse score configs from a repository contract

**Decision**: Add `evals/score-contracts/foundation.v1.yaml`, validate it locally, reconcile matching
Langfuse score configs during preflight, and pass each config ID when publishing a score.

**Rationale**: Langfuse score configs enforce name, type, range/categories, and make historical
scores comparable. Configs are immutable. An incompatible semantic change must use a new canonical
score name; additive contract revisions may retain unchanged names/config IDs.

**Alternatives considered**:

- Scores without configs: rejected because name/type drift would be possible.
- Store the score contract only in Langfuse: rejected because repository review is authoritative.
- Encode contract version only in metadata: rejected because it does not enforce value shape.

References: [Scores data model](https://langfuse.com/docs/evaluation/scores/data-model),
[Scores via SDK](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)

## Decision 8: Reuse the agent's deterministic citation validation result

**Decision**: Project `AgentState.answer_validation` into a sanitized citation observation. Do not
rerun or replace citation validation with a judge.

**Rationale**: The existing validator already checks unknown citations, missing material-claim
citations, company, period, unit, number, correlation, and calculation lineage. Reuse keeps online
and evaluation semantics aligned. Only booleans, counts, evidence IDs, and stable reason codes are
needed; raw answers and evidence passages stay out of artifacts and comments.

**Alternatives considered**:

- Revalidate from serialized raw answer/evidence: rejected because it expands sensitive artifacts.
- Keyword citation checks: rejected because they lose lineage semantics.
- LLM-as-judge citation scoring: deferred to feature 004 and unnecessary for deterministic checks.

## Decision 9: Separate execution state, gate state, and workflow exit code

**Decision**:

- Execution: `completed`, `partial`, or `errored`.
- Gate: `passed`, `failed`, or `not_evaluated`.
- CLI exit: `0` passed, `1` evaluated quality failure, `2` infrastructure/not-evaluated failure.

**Rationale**: A completed experiment may legitimately fail quality thresholds. Infrastructure
failure must fail the workflow without being mislabeled as an agent regression.

**Alternatives considered**:

- One `passed` boolean: rejected because it conflates quality and operability.
- Treat every missing result as quality failure: rejected when the evaluator/provider itself failed.
- Neutral workflow exit for infrastructure errors: rejected because manual reviewers need visibility.

## Decision 10: Use privacy-safe experiment outputs and summaries

**Decision**: Langfuse experiment task output and local/public artifacts contain the observed
contract, not the final answer. Failure details use allowlisted reason codes and bounded messages.

**Rationale**: The existing telemetry policy excludes raw prompts/provider payloads by default, but
the experiment runner explicitly records task input/output. Golden user conversations are reviewed
dataset inputs; generated answers, retrieved passages, provider errors, and invalid drafts are not
required to evaluate deterministic behavior.

**Alternatives considered**:

- Store final answers for easier debugging: rejected by the approved privacy boundary.
- Store raw exception strings: rejected because provider and database details may leak.
- Store only one pass/fail bit: rejected because route/check/reason detail is needed for diagnosis.

## Decision 11: Split oversized evaluation and CLI modules before extending them

**Decision**: Extract typed models, checks, gates, reporting, state projection, Langfuse sync,
experiment adapter, orchestration, and eval CLI handlers into focused modules. Keep a compatibility
facade for existing deterministic imports.

**Rationale**: `deterministic.py` is 958 lines, `agent_runner.py` is 331 lines, and `cli.py` is 1,163
lines. The feature adds several independent responsibilities and the repository explicitly asks for
cohesive splits before modifying files over 250 lines.

**Alternatives considered**:

- Add all behavior to current modules: rejected because it worsens ownership and test isolation.
- New standalone service: rejected because the workload is manual, repository-driven, and already
  has the required CLI, agent, database, and telemetry boundaries.
