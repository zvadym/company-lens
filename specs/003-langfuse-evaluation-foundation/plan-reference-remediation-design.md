# Plan Reference Alias Remediation

**Date**: 2026-07-15  
**Feature**: `003-langfuse-evaluation-foundation`  
**Status**: Implemented and live-validated

## Context

Live evaluation execution `a99784d2-d742-461e-b9e4-6aa0e20f0525` exposed a planner-output
variation in `followup_replace_company_preserve_task_001`. The model produced a financial source
with branch ID `revenue_last_five_quarters` and dataset alias `revenue_qoq_input`, then used the
alias as the calculation input reference. The domain conversion discarded source dataset aliases,
and plan validation indexed the branch map directly with the alias, raising
`KeyError: 'revenue_qoq_input'`.

The evaluation runner correctly classified the uncaught exception as infrastructure and left the
gate not evaluated. The underlying issue is nevertheless deterministic application behavior:
semantically coherent model output can use either a branch ID or the source's dataset alias.

## Goals

1. Accept a unique source `dataset_ref` as an alias for that source's canonical `branch_id`.
2. Canonicalize calculation, dependency, and chart references before constructing the domain plan.
3. Preserve `branch_id` as the only reference stored in the domain `ExecutionPlan`.
4. Convert unknown or ambiguous references into controlled validation errors, never `KeyError`.
5. Cover the exact live-output shape with deterministic regression tests.

## Non-Goals

- Retrying internal plan-conversion bugs as provider failures.
- Weakening plan dependency, source-kind, or single-series validation.
- Changing evaluation gate thresholds or infrastructure classification.
- Expanding the model planning schema into separate branch unions.

## Considered Approaches

### A. Canonicalize unique dataset aliases

Build an alias map from source branches before domain conversion. Rewrite references that match a
unique alias to the source branch ID, while leaving existing branch-ID references unchanged. Reject
aliases that collide with another branch ID or identify multiple sources.

**Decision**: Selected. It accepts the model's semantically coherent variation while keeping the
domain graph canonical and deterministic.

### B. Prompt-only enforcement

Strengthen the planning prompt to require branch IDs in every reference field.

**Decision**: Rejected. Prompts reduce frequency but cannot enforce the invariant, and this exact
output already passed structured schema validation.

### C. Reject every alias reference

Treat the model output as invalid and use the existing fallback path.

**Decision**: Rejected. A deterministic alias can be resolved safely, and the single-company growth
path does not always have a behavior-preserving fallback.

## Design

`_domain_execution_plan` gathers branch IDs and source aliases before converting individual
branches. Branch IDs are authoritative:

- a reference matching an existing branch ID is unchanged;
- otherwise, a reference matching one unique source alias becomes that source's branch ID;
- a source alias shared by multiple branches is invalid;
- a source alias colliding with a different branch ID is invalid;
- any remaining unknown reference is rejected during normal domain validation.

Canonicalization applies to `depends_on`, calculation `input_refs`, and chart `dataset_ref`. Source
aliases are not added to the domain models and therefore cannot leak into execution, persistence,
or evaluation output.

Plan validation replaces direct branch-map indexing with explicit lookup. Missing calculation or
chart references raise a bounded `ValueError` containing only the invalid reference category. The
existing `plan_request` error path can then return a sanitized terminal result or use an available
deterministic fallback.

## Testing

- Reproduce the exact live plan shape and assert the calculation references the financial source's
  canonical branch ID after conversion and validation.
- Prove an already canonical branch-ID reference remains unchanged.
- Prove duplicate/colliding aliases fail deterministically.
- Prove an unknown calculation or chart reference raises `ValueError`, not `KeyError`.
- Run the focused agent workflow tests, full local quality gate, and a live follow-up evaluation.

## Success Criteria

- `followup_replace_company_preserve_task_001` no longer produces
  `agent_execution_failed` for the observed alias variation.
- No domain `ExecutionPlan` contains source dataset aliases in dependency/reference fields.
- All existing plan validation and evaluation tests remain green.
- The targeted live follow-up run completes with a passed gate before another full run is accepted.

## Validation Evidence

- Regression tests reproduce the exact `revenue_qoq_input` alias shape, canonical chart aliases,
  duplicate aliases, and unknown references.
- Local validation passed Ruff, formatting, strict mypy for 170 source files, and pytest with
  `404 passed, 3 skipped`.
- Targeted follow-up workflow `29445519088` completed all four cases with
  `gate_status=passed`; Langfuse run `56a0b560-437a-439a-9c77-22ae922a141b` contains four unique
  item traces.
- Full workflow `29445921451` completed all 18 cases with `gate_status=passed`, zero infrastructure
  outcomes, and zero failed citation validations.
- The canonical Langfuse runs contain exactly 14 core and four follow-up item-to-trace links, with
  run IDs matching the immutable execution artifact.
