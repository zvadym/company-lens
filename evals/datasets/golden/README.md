# Golden Evaluation Datasets

<!-- Keep this directory framework-neutral; adapters should consume it, not define truth. -->

This directory contains framework-neutral CompanyLens evaluation cases.

The cases are the reviewed source of truth for deterministic evaluators and remote adapters.
Adapter-specific records must be generated from these cases instead of duplicating expectations.

## Dataset Slices

- `core.v1.yaml` contains the single-turn coverage set across financial facts, document
  retrieval, hybrid analysis, ambiguity, abstention, adversarial handling, and
  cross-document comparison.
- `follow_up.v1.yaml` contains the multi-turn evaluation set for research-session memory,
  safe context reuse, target replacement, and abstention on unresolved companies.

## Case Design Rules

- Describe user-visible and system-level expected behaviour before low-level implementation details.
- Use stable company names, tickers, source IDs, metric names, and operation names.
- Record what may be inherited from previous turns separately from what must not be inherited.
- Prefer `abstain_or_clarification` when the safe behaviour is to avoid answering until the
  user supplies a verifiable public-company target.
- Keep this dataset independent of any evaluation framework.
- Keep the combined foundation between 18 and 25 cases, with at least two cases in every category.
- Every case resolves to `citation_mode: required|not_applicable`; omission remains backward
  compatible and means `required`.
- Use `not_applicable` only when the expected response has no material source-derived claim.
- Citation-required coverage must include `valid`, `missing_attempt`,
  `unknown_evidence_attempt`, and `semantic_mismatch_attempt`. Challenge scenarios describe the
  invalid behavior the agent must resist; they still expect a citation-valid final answer.

## Langfuse Synchronization

Repository paths, versions, case IDs, and canonical hashes produce deterministic UUIDv5 item IDs.
An explicit `sync-evaluation-datasets` run upserts every active repository case, archives mapped
remote items no longer present here, reconciles the versioned score contract, and verifies an exact
timestamp-pinned snapshot. A dry run performs no project lookup or remote write. Langfuse remains a
visible execution and comparison surface; edits made there never replace reviewed repository truth.
