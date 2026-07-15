# Follow-up Correctness and Preparation Efficiency Remediation

**Date**: 2026-07-15  
**Feature**: `003-langfuse-evaluation-foundation`  
**Status**: Approved design, pending implementation plan

## Context

The first full 18-case live evaluation and the targeted follow-up rerun separated evaluator defects
from production-agent defects. Evaluator remediation raised follow-up `operation_accuracy` from
`0.0` to `1.0` and removed ticker-alias false negatives, but three genuine failures remained:

- replace-company follow-ups lost the inherited `revenue` metric;
- add-company follow-ups retained only the new company instead of extending the previous set;
- financial-only follow-ups exceeded operational budgets because company preparation performed SEC
  filing ingestion, document processing, and embedding work that the route did not need.

Langfuse trace analysis for `followup_add_company_to_comparison_001` showed `242,308` total model
tokens. Embeddings accounted for `230,612` tokens; answer and structured generations accounted for
`11,696`. The same trace also showed duplicate company-extraction generations caused by resolving
the question again after preparation.

## Goals

1. Make follow-up company-set behavior deterministic for inherit, replace, and extend intents.
2. Preserve inherited metrics and calculation operation across compatible follow-up turns.
3. Record company provenance per target, including mixed previous/new company sets.
4. Make on-demand company preparation execute only the data pipelines required by the analyzed
   capabilities.
5. Remove duplicate LLM company extraction after company preparation.
6. Keep operational evaluation limits strict and continue reporting actual generation and embedding
   usage through Langfuse.

## Non-Goals

- Changing evaluation gate thresholds to make current failures pass.
- Prewarming every evaluation company to hide production preparation cost.
- Replacing structured planning with a fully deterministic planner.
- Adding LLM-as-judge, annotation queues, or judge calibration; those remain feature `004` scope.
- Changing document and hybrid routes so they stop preparing required SEC evidence.

## Considered Approaches

### A. Capability-aware preparation plus deterministic follow-up merge

Derive preparation requirements from `QuestionAnalysis.required_capabilities`, preserve explicit
current-turn company identity before merging, and use deterministic follow-up intent rules. This
fixes production behavior and keeps evaluation representative.

**Decision**: Selected.

### B. Prompt-only remediation

Adjust parse and planning prompts to ask the model to preserve context. This has a smaller code
change but leaves correctness dependent on generated reason codes and does not prevent unnecessary
document preparation.

**Decision**: Rejected because it does not provide a stable invariant.

### C. Evaluation-only prewarming or budget adjustment

Prepare all companies before each run or increase follow-up limits. This improves CI results while
leaving the production agent expensive and context handling incorrect.

**Decision**: Rejected because it hides the defects the evaluation is intended to expose.

## Architecture

### Preparation requirements

Introduce an ingestion-owned immutable requirement model with two independent flags:

- `financial_facts`: company identity and structured financial facts are required;
- `documents`: SEC filings, processed chunks, and embeddings are required.

The workflow maps agent capabilities to these requirements:

| Agent capabilities | Financial facts | Documents |
| --- | --- | --- |
| `financial_facts`, optionally `calculations`/`chart` | yes | no |
| `documents` only | no | yes |
| `documents` and `financial_facts` | yes | yes |
| unsupported or no company-data capability | no | no |

Document preparation may still establish company identity as part of SEC ingestion. A
financial-only request must not ingest filings, process documents, or create embeddings.

`OnDemandCompanyDataPreparer` evaluates readiness against the requested requirements. A ticker with
financial facts but no indexed chunks is ready for facts-only preparation and not ready for a
document request.

### Follow-up intent

Follow-up company-set behavior uses current resolved company mentions plus deterministic language
markers. Model reason codes remain an additional signal but are not the sole control input.

| Current turn | Result |
| --- | --- |
| No explicit company | Inherit the previous compatible company set |
| Explicit company without add/include intent | Replace the previous company set |
| Explicit company with add/include intent | Extend the previous compatible company set |

The existing multilingual add markers remain supported. Repeated company IDs are deduplicated while
preserving previous-set order followed by new current-turn companies.

### Per-company provenance

Entity resolution retains the pre-merge current query while producing the merged query. Research
frame construction receives both:

- a company present in the pre-merge current query receives `current_question`;
- a company introduced only by the merge receives `follow_up_context`;
- prepared tickers introduced from the current turn retain `prepared_ticker` where that existing
  source contract applies.

Provenance is assigned per target. A single frame can therefore represent NET and DDOG from
follow-up context and MDB from the current question.

### Metric and operation inheritance

The merged `ResolvedQuery` uses current metrics when explicitly present and otherwise inherits the
previous compatible metrics. Calculation operation continues to come from the current execution
plan, with `ResearchFrame.follow_up_operation` as the deterministic inherited fallback.

Observation projection remains unchanged: it reads metrics from the final frame query and the
operation from the plan or frame fallback. Correct state, rather than evaluator compensation, must
produce the passing result.

### Post-preparation resolution

Preparation must not rerun model-based company extraction. After preparation or a readiness skip,
the workflow resolves returned tickers through the deterministic local entity resolver and merges
those company IDs/entities into the already-resolved current query. Follow-up merging then runs once
against that enriched query.

This removes the duplicate `entity_extraction` generation while preserving the ability to convert a
public ticker placeholder into a local company row after ingestion.

## Data Flow

1. `parse_question` produces route and required capabilities.
2. Initial entity resolution produces the current-turn `ResolvedQuery`.
3. The workflow derives preparation requirements from capabilities.
4. On-demand preparation executes only missing required pipelines.
5. Prepared/skipped tickers are resolved locally without another LLM extraction.
6. Follow-up intent merges current and previous queries using inherit, replace, or extend semantics.
7. Research frame construction assigns source per target from current versus inherited identity.
8. Planning and tools consume the final merged query.
9. Evaluation projects the final state and records all actual usage in Langfuse.

No new graph node is required. `resolve_entities` retains the unmerged current-turn query, and
`prepare_company_data` always performs the deterministic merge/frame finalization before planning,
including when no external preparation work is required.

## Error Handling

- Missing or contradictory analysis does not trigger document preparation without an explicit
  `documents` capability.
- A facts-only preparation failure produces the existing sanitized partial/missing-data behavior;
  it does not fall through to document ingestion.
- A document-pipeline failure preserves any successfully prepared financial facts and reports the
  document failure through the existing preparation result.
- Readiness checks are scoped. Missing unrequested data is neither a failure nor a reason to run an
  additional pipeline.
- Deterministic ticker resolution failure leaves the existing unresolved target behavior intact.
- Structured model output validation continues to use the bounded recoverable retry added after the
  first full live run.

## Observability

- Existing preparation trajectory details remain, including facts, filings, documents, chunks, and
  failures.
- Add the selected preparation requirements to privacy-safe preparation span/event details.
- Do not suppress embedding usage when documents are required; operational metrics remain actual
  aggregate usage for the complete case conversation.
- Existing Langfuse item and run scores remain unchanged.
- No raw prompts, model payloads, answer drafts, passages, or credentials enter public artifacts.

## Testing

### Ingestion tests

- Facts-only preparation invokes company-facts ingestion and does not invoke SEC ingestion,
  document processing, or embedding indexing.
- Documents-only preparation invokes the document pipeline without requiring facts readiness.
- Combined preparation invokes both required pipelines.
- Readiness depends only on the selected requirements.

### Workflow tests

- A company-free follow-up inherits company, metric, and operation.
- `Do the same for Datadog` replaces Cloudflare while preserving revenue and QoQ growth.
- `Add MongoDB too` returns Cloudflare, Datadog, and MongoDB in stable order.
- Mixed target sources are `follow_up_context`, `follow_up_context`, and `current_question`.
- Prepared ticker enrichment does not call LLM company extraction a second time.
- Financial-only analysis passes facts-only requirements to the tools adapter.
- Document and hybrid analysis retain document preparation.

### Verification

1. Run focused ingestion, workflow, and evaluation regression tests.
2. Run `make check`.
3. Run `graphify update .`.
4. Run the four-case follow-up workflow and inspect case scores plus operational details in Langfuse.
5. Run the full 18-case workflow only after the follow-up run is trustworthy.

## Acceptance Criteria

- All four follow-up cases complete without evaluation infrastructure errors.
- `company_accuracy`, `metric_accuracy`, `operation_accuracy`, `follow_up_safety_accuracy`, and
  `citation_validity_pass_rate` are `1.0` for the targeted follow-up run.
- Financial-only follow-up traces contain no document-processing or embedding operations.
- No turn performs a second model-based company extraction solely because preparation completed or
  skipped.
- The add-company case preserves prior companies and identifies the new company as current-turn
  context.
- Operational budgets pass without increasing gate thresholds.
- Document and hybrid regression tests continue to prepare and use SEC evidence.

## Rollout

Implement behind existing workflow boundaries without a feature flag. Validate locally, then push to
the existing PR and run follow-up-only evaluation. If that run passes, execute all 18 cases. If it
fails, use the new preparation scope and per-company provenance signals in Langfuse to distinguish a
state defect from a data-readiness defect before making further changes.
