# Operation Reconciliation Contract

## Purpose

Define the internal structured boundary that reconciles LLM-owned calculation intents with planner
calculation branches before deterministic tools execute. This contract does not expose a public API
or persist a new database entity.

## Trigger

`reconcile_operations` runs after `plan_request` and before `hydrate_cached_results`.

The model call is skipped when all effective typed intents and calculation branches are compatible.
Exactly one bounded reconciliation call sequence is permitted when the structured detector reports
an operation, metric, explicit-parameter, inheritance, missing-intent, or ambiguous-association
conflict.

The detector MUST NOT inspect free-form user text or use phrase dictionaries.

## Input

The reconciliation prompt receives a canonical JSON object containing:

```json
{
  "question": "current user question",
  "effective_intents": [
    {
      "operation": "quarter_over_quarter_growth",
      "metrics": ["revenue"],
      "window": 8,
      "years": null,
      "base": null,
      "source": "current"
    }
  ],
  "conflict_reason_codes": ["operation_conflict"],
  "calculation_branches": [
    {
      "branch_id": "cloudflare_growth",
      "operation": "percentage_change",
      "metrics": ["revenue"],
      "input_count": 1,
      "window": null,
      "years": null,
      "base": 100
    }
  ],
  "policy": {
    "max_retries_per_node": 2
  }
}
```

The prompt may include the current question so the reconciliation LLM can adjudicate semantics. It
MUST NOT include previous answer prose, retrieved passages, evidence payloads, credentials, hidden
reasoning, or raw provider errors.

## Output

The response schema is `OperationReconciliation`:

```json
{
  "branch_operations": [
    {
      "branch_id": "cloudflare_growth",
      "operation": "quarter_over_quarter_growth",
      "window": 8,
      "years": null,
      "base": null
    }
  ]
}
```

Required response invariants:

1. Every existing calculation branch appears exactly once.
2. No unknown, source, or chart branch appears.
3. No branch ID appears twice.
4. The response contains no topology, source-request, company, metric, dependency, or input fields.
5. Required scalar parameters are present and valid for the selected operation.

## Application

The workflow applies decisions by copying each existing calculation branch and updating only:

- `operation`;
- `window`;
- `years`;
- `base`.

`window` and `years` are applied exactly, including null to clear an irrelevant value.
`base=null` preserves the existing non-null branch base; a non-null base replaces it.

The workflow then verifies topology equality against the pre-reconciliation plan, re-runs structured
intent conflict detection, and executes full domain plan validation. Cache hydration and tools remain
unreachable until every check passes.

## Failure Contract

| Failure | Agent outcome | Evaluation gate | Workflow exit |
|---|---|---|---|
| timeout, connection, 429, 500 | provider infrastructure error | `not_evaluated` | `2` |
| refusal or schema-invalid response after retries | provider response infrastructure error | `not_evaluated` | `2` |
| missing/duplicate/unknown decision | `operation_reconciliation_failed` behavior error | `failed` | `1` |
| incompatible arity/parameter | `operation_reconciliation_failed` behavior error | `failed` | `1` |
| remaining typed conflict | `operation_reconciliation_failed` behavior error | `failed` | `1` |

No failure path selects parser or planner output as a fallback after a conflict has been detected.
No failure path executes tools for the affected plan.

## Observability Contract

The agent trajectory records:

- node `reconcile_operations`;
- status `skipped`, `completed`, or `failed`;
- whether reconciliation was required;
- sanitized conflict reason codes/count;
- decision count;
- attempts and duration.

The existing model-generation instrumentation records the dedicated
`operation_reconciliation` purpose, repair model, prompt metadata, tokens, latency, and retries in
the active Langfuse item trace. Public observations and evaluation artifacts expose only typed final
operations, counts, and allowlisted reason codes.
