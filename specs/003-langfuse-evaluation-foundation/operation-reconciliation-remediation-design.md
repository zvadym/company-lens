# LLM Calculation Operation Reconciliation Remediation

**Date**: 2026-07-16  
**Feature**: `003-langfuse-evaluation-foundation`  
**Status**: Approved design, implementation plan complete

## Context

Live evaluation workflow `29476087090` completed nine selected cases and correctly failed its
quality gate. All five core cases passed. Three of four follow-up cases passed. The remaining case,
`followup_add_company_to_comparison_001`, resolved NET, DDOG, and MDB correctly, preserved the
`revenue` metric, used the expected route and tools, stayed within operational budgets, and produced
valid citations. Its only failure was the calculation operation.

The user asked for quarter-over-quarter revenue growth. The parse model emitted
`qoq_growth_requested`, and the plan branch titles also described quarter-over-quarter growth, but
the planning model selected `percentage_change`. The follow-up turn correctly inherited that
incorrect operation. A previous run of the same code selected `quarter_over_quarter_growth` and
passed, proving that the remaining defect is model-output variability rather than an evaluator,
provider, or alias-normalization failure.

## Goals

1. Keep calculation-operation interpretation LLM-owned; do not add keyword dictionaries or
   deterministic natural-language matching.
2. Represent the parser's operation interpretation as typed calculation intents.
3. Detect parser, session-memory, and planner disagreement using structured fields only.
4. Invoke a narrow LLM reconciliation step only when a structured conflict exists.
5. Allow reconciliation to change operation and operation parameters without changing plan
   topology, source requests, dependencies, or inputs.
6. Fail closed when reconciliation cannot produce a trustworthy compatible result.
7. Make every reconciliation decision, call, retry, and outcome inspectable in Langfuse without
   weakening privacy-safe public artifacts.

## Non-Goals

- Searching user text for QoQ, YoY, CAGR, margin, or other operation phrases in Python.
- Adding or maintaining phrase-to-operation dictionaries.
- Allowing reconciliation to create, delete, or reorder execution branches.
- Allowing reconciliation to change branch IDs, dependencies, input references, companies,
  metrics, or source requests.
- Running reconciliation for already consistent calculation plans.
- Adding LLM-as-judge or judge calibration; those remain feature `004` scope.
- Changing evaluation thresholds to tolerate operation variability.

## Considered Approaches

### A. Deterministic phrase mapping

Search normalized user text for known phrases and force the corresponding operation.

**Decision**: Rejected. The product requirement is that the LLM owns semantic operation
interpretation, and phrase dictionaries do not scale reliably across wording and language.

### B. Separate LLM reconciliation on structured conflict

Have the parse model emit typed calculation intents, compare them with the final planner branches,
and invoke one narrow repair-model call only when the typed structures disagree.

**Decision**: Selected. It preserves LLM semantic ownership, isolates the correction task, avoids a
new call on consistent plans, and gives Langfuse a distinct reconciliation observation.

### C. Retry the complete planner

Reject any mismatch and rerun the full planning prompt.

**Decision**: Rejected. It is more expensive, can reproduce the same mismatch, and allows unrelated
parts of an otherwise valid plan to change.

### D. Reconcile every calculation plan

Run an independent semantic check for every plan containing calculation branches.

**Decision**: Rejected. It adds latency and cost to already consistent plans without improving the
specific conflict boundary.

## Typed Intent Contract

`QuestionAnalysis` and its provider DTO gain typed calculation intent state:

```text
CalculationIntent
  operation: CalculationOperation
  metrics: string[]
  window: integer | null
  years: decimal | null
  base: decimal | null

QuestionAnalysis
  calculation_intents: CalculationIntent[]
  inherit_previous_calculation_intents: boolean
```

Rules:

- `calculation_intents` may contain multiple operations for a mixed calculation request.
- `metrics` associates an intent with compatible planner inputs, including two-input operations such
  as margin or correlation; an empty tuple means the parser cannot identify a metric constraint.
- Null parameters mean the user did not specify that applicable parameter; they do not conflict with
  a compatible planner default.
- `window` is required and non-null only for `rolling_average`; source-selection periods such as
  "last eight quarters" remain in the typed source request and never use calculation `window`.
- `years` is required and non-null only for `cagr`; `base` may be non-null only for
  `normalised_index`. These applicable non-null values are authoritative intent constraints.
- A vague compatible follow-up such as `Add MongoDB too` emits no new explicit intents and sets
  `inherit_previous_calculation_intents=true`.
- A follow-up that explicitly requests a new operation emits explicit intents and does not inherit
  the prior operation for those intents.
- Requests without calculation intent use an empty tuple and `false` inheritance flag.
- The parser remains an LLM structured-output call. Python does not infer these fields from text.

For backward compatibility during migration, repository-created analysis fixtures may omit the new
fields and receive empty/false defaults. Provider-facing prompts and contract tests must require
correct typed intent output for calculation requests and compatible follow-ups.

## Effective Intent Resolution

Before conflict detection, the workflow builds effective intents:

1. Use explicit current-turn intents when present.
2. When inheritance is requested, derive inherited intents from the final validated previous
   execution plan in session memory.
3. Never inherit from the planner's pre-reconciliation draft.
4. Do not use previous answers, raw evidence, or generated prose to infer operations.
5. If a calculation plan exists but neither explicit nor inherited typed intent is available, mark
   the plan as requiring reconciliation rather than guessing from text.

One effective intent may apply to multiple company-specific branches sharing the same compatible
metrics and operation. Multiple effective intents may map to separate branch groups in one plan.

## Structured Conflict Detection

Conflict detection receives only typed intents, the validated branch graph, typed source requests,
and final previous-plan operation summaries. It does not receive or inspect free-form user text.

A conflict exists when any of the following is true:

- a planner calculation operation is not represented by a compatible effective intent;
- an effective intent is not represented by a compatible calculation branch;
- a planner operation is associated with the wrong metric;
- an applicable explicit intent parameter conflicts with planner `window`, `years`, or `base`, or an
  inapplicable scalar is non-null;
- the parser requests inheritance but the planner changes the inherited operation or explicit
  parameters;
- a calculation plan has no effective typed intent;
- typed intent-to-branch association is incomplete or ambiguous.

No reconciliation call occurs when every calculation branch is compatible with the effective
intents and every effective intent is represented. A single intent can authorize the same operation
across multiple company branches without a cardinality conflict.

## Workflow Architecture

Add a dedicated `reconcile_operations` node after `plan_request` and before result hydration and
tool execution:

```text
parse_question
  -> resolve_entities
  -> prepare_company_data
  -> plan_request
  -> reconcile_operations
  -> hydrate_cached_results
  -> tool execution
```

The node behavior is:

1. Resolve effective calculation intents.
2. Compare effective intents with calculation branches.
3. Return a skipped trajectory event when no conflict exists.
4. On conflict, call the configured repair model once through the existing bounded structured-call
   retry helper with `ModelPurpose.OPERATION_RECONCILIATION`.
5. Validate the reconciliation response against the original branch graph.
6. Apply only operation and scalar parameter updates.
7. Re-run complete domain plan validation before any tool executes.
8. Persist only the final reconciled plan to session memory.

The new model purpose routes to the existing repair-model configuration; no new model environment
setting is required. It remains a distinct purpose and observation in telemetry and Langfuse.

## Reconciliation Contract

The reconciler receives:

- the current user question for semantic adjudication by the LLM;
- typed current/effective calculation intents;
- privacy-safe summaries of calculation branches and numeric source metrics;
- parser and planner operation/parameter values;
- inherited final-plan operation summaries when applicable;
- the execution policy.

It does not receive final-answer prose, retrieved passages, credentials, hidden reasoning, or raw
provider payloads.

The response contains one decision for every calculation branch:

```text
OperationReconciliation
  branch_operations: BranchOperationDecision[]

BranchOperationDecision
  branch_id: string
  operation: CalculationOperation
  window: integer | null
  years: decimal | null
  base: decimal | null
```

Validation requires:

- every existing calculation branch appears exactly once;
- every returned branch ID identifies an existing calculation branch;
- no source or chart branch appears;
- branch count, ordering, IDs, dependencies, and input references remain unchanged;
- source requests, companies, metrics, and retrieval configuration remain unchanged;
- operation input arity remains compatible with the unchanged inputs;
- required parameters are present for operations such as CAGR and rolling average;
- parameter values satisfy existing domain bounds and are null for operations to which they do not
  apply;
- decision `window` and `years` are applied exactly, including null to clear an irrelevant value;
  decision `base=null` preserves the branch's existing non-null base, while a non-null base replaces
  it;
- the reconciled plan represents every effective intent without new conflicts.

The reconciler cannot repair an incompatible topology. It fails closed instead.

## Error Handling

### No conflict

- `reconcile_operations` is skipped.
- No model call, token usage, or retry is added.
- Trajectory records `operation_reconciliation_not_required`.

### Provider or response infrastructure failure

A model refusal immediately takes the provider-response infrastructure path without retry. Timeout,
connection failure, 429, 500, or schema-invalid structured output follows the existing recoverable
policy and reaches this path after bounded retries are exhausted:

- preserve the existing provider error category and sanitized failure code;
- evaluation classifies the case as infrastructure;
- execution is partial or errored;
- gate is `not_evaluated`;
- workflow exits `2`;
- no tools execute for the affected case.

### Semantically invalid reconciliation

A schema-valid response with missing, duplicate, unknown, incompatible, or still-conflicting branch
decisions:

- return a validation-category terminal error with code
  `operation_reconciliation_failed`;
- evaluation records an observed behavior failure;
- the quality gate fails and workflow exits `1`;
- no tools execute for the affected case.

No failure path falls back to the parser or planner operation after a detected conflict.

## Observability And Privacy

Langfuse must expose:

- parser calculation intents and inheritance mode as privacy-safe structured metadata;
- whether conflict detection was required;
- sanitized conflict categories, not free-form reasoning;
- a dedicated reconciliation generation with purpose `operation_reconciliation`;
- reconciliation attempts, latency, model, token usage, and retry count;
- final branch operations and parameters;
- terminal provider-versus-behavior failure classification.

Operational metrics include reconciliation API calls, latency, tokens, and retries. Existing policy
budgets remain unchanged until measured live evidence justifies a reviewed change.

Public execution artifacts and PR comments must not include raw prompts, raw model responses,
provider payloads, hidden reasoning, retrieved passages, or credentials. They may include stable
reason codes and aggregate operational metrics.

## Testing Strategy

### Schema tests

- single and multiple explicit calculation intents;
- inherited-intent mode;
- optional and required scalar parameters;
- invalid combinations and bounds;
- backward-compatible defaults for repository fixtures.

### Conflict detector tests

- consistent parser and planner state produces no reconciliation call;
- exact live failure: parser QoQ versus planner `percentage_change`;
- one intent maps to multiple company branches;
- multiple operations map to separate branch groups;
- metrics and scalar-parameter conflicts;
- compatible follow-up inherits final previous-plan operations;
- missing or ambiguous effective intents require reconciliation.

### Reconciliation validation tests

- valid operation and parameter updates preserve topology byte-for-byte;
- missing, duplicate, and unknown branch IDs fail;
- source/chart branch IDs fail;
- changed dependencies or input references are impossible through the response schema and verified
  unchanged after application;
- incompatible arity and missing required parameters fail;
- a still-conflicting final plan fails.

### Failure taxonomy tests

- timeout, 429, 500, and schema-invalid exhaustion become infrastructure/not-evaluated;
- schema-valid semantic incompatibility becomes observed `operation_reconciliation_failed`;
- provider retries and usage enter operational metrics;
- no tool executes after either failure class.

### End-to-end regression

Use a queued fake model sequence:

1. Parse the initial comparison as QoQ revenue growth.
2. Return a planner plan using `percentage_change` for all company branches.
3. Reconcile every calculation branch to `quarter_over_quarter_growth`.
4. Complete the initial turn and persist only the reconciled plan.
5. Parse `Add MongoDB too` as inherited calculation intent.
6. Verify NET, DDOG, and MDB; revenue; QoQ; required tools; valid citations; and no second
   reconciliation when the inherited follow-up plan is already consistent.

### Live rollout

1. Run focused schema, workflow, evaluation, and observability tests.
2. Run `graphify update .` and the full local `make check` gate.
3. Run `dataset_scope=follow_up` and require 4/4 cases plus every deterministic metric at `1.0`.
4. Inspect Langfuse conflict/no-conflict traces and canonical four-item linkage.
5. Run `dataset_scope=all` and require 18/18 cases, 14+4 canonical links, zero infrastructure
   outcomes, and all pass rates at `1.0` except `missing_result_rate=0.0`.
6. Keep PR `#68` in Draft until both live runs pass and evidence is appended to the quickstart.

## Success Criteria

- The exact QoQ-versus-`percentage_change` regression is corrected by the reconciliation model, not
  by a phrase dictionary.
- Consistent calculation plans incur zero reconciliation model calls.
- Reconciliation cannot change plan topology or source selection.
- Provider failures and semantic failures retain distinct evaluation taxonomy.
- Follow-up operation inheritance uses only the previous final reconciled plan.
- Targeted and full live evaluations pass without threshold changes.
- Langfuse makes the intent, conflict, reconciliation, final operation, usage, and outcome visible.
