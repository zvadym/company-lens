# Golden Evaluation Datasets

<!-- Keep this directory framework-neutral; adapters should consume it, not define truth. -->

This directory contains framework-neutral CompanyLens evaluation cases.

The cases are the source of truth for custom pytest evaluators and future adapters
such as Ragas, DeepEval, LangSmith, Langfuse, or Phoenix. Adapter-specific files
should be generated from these cases instead of duplicating expected behaviour.

## Dataset Slices

- `core.v1.yaml` starts the single-turn coverage set across financial facts, document
  retrieval, hybrid analysis, ambiguity, abstention, adversarial handling, and
  cross-document comparison.
- `follow_up.v1.yaml` starts the multi-turn evaluation set for research-session memory,
  safe context reuse, target replacement, and abstention on unresolved companies.

## Case Design Rules

- Describe user-visible and system-level expected behaviour before low-level implementation details.
- Use stable company names, tickers, source IDs, metric names, and operation names.
- Record what may be inherited from previous turns separately from what must not be inherited.
- Prefer `abstain_or_clarification` when the safe behaviour is to avoid answering until the
  user supplies a verifiable public-company target.
- Keep this dataset independent of any evaluation framework.
