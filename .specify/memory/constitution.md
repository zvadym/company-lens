<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- [PRINCIPLE_1_NAME] -> I. Evidence-First Answers
- [PRINCIPLE_2_NAME] -> II. Deterministic Data Paths
- [PRINCIPLE_3_NAME] -> III. Source Lineage And Citation Safety
- [PRINCIPLE_4_NAME] -> IV. Durable Research Sessions
- [PRINCIPLE_5_NAME] -> V. Observable, Tested Delivery
Added sections:
- Product Constraints
- Development Workflow
Removed sections:
- None
Templates requiring updates:
- Updated: .specify/templates/plan-template.md
- Reviewed: .specify/templates/spec-template.md
- Reviewed: .specify/templates/tasks-template.md
Follow-up TODOs:
- None
-->
# CompanyLens Constitution

## Core Principles

### I. Evidence-First Answers
CompanyLens MUST answer public-company research questions from bounded evidence envelopes,
not from ungrounded model memory. Every generated answer that states a factual claim MUST be
backed by retrieved documents, structured facts, macro observations, deterministic
calculations, or an explicit abstention.

### II. Deterministic Data Paths
Questions about numerical facts, periods, growth, margins, correlations, and chartable
series MUST prefer structured SEC facts, FRED observations, and deterministic calculations
over prose retrieval. Narrative retrieval is appropriate for qualitative filing evidence,
management commentary, risks, strategy, and outlook.

### III. Source Lineage And Citation Safety
All source-derived data MUST retain provenance sufficient to explain company, period, unit,
source URL, accession or document identity, page or section when available, and calculation
lineage. Citation validation MUST reject unknown evidence IDs, wrong companies, wrong
periods, unsupported numbers, unsafe correlation claims, and incomplete calculation lineage.

### IV. Durable Research Sessions
Research runs MUST be resumable, cancellable, inspectable, and safe across process restarts.
PostgreSQL-backed dev data is the source of truth for development checks. Local SQLite files
or generated artifacts MUST NOT be treated as authoritative dev state.

### V. Observable, Tested Delivery
Changes MUST preserve typed contracts, public error boundaries, privacy-safe execution
traces, and focused automated tests. Non-obvious state transitions, fallbacks, invariants,
and domain assumptions MUST be documented with succinct code comments.

## Product Constraints

CompanyLens is an agentic public-company intelligence system. Feature specifications MUST
distinguish among document retrieval, structured financial facts, macro observations,
calculations, chart artifacts, session memory, and UI trace/source presentation.

All development commands or database checks that depend on dev data MUST verify `.env`
exists first and MUST use the Docker dev stack started by `make start-dev-docker`.
External provider credentials, raw prompts, provider payloads, exception internals, raw
retrieved passages, and hidden reasoning MUST NOT be exposed through public APIs or SSE
trace events.

## Development Workflow

Specs SHOULD start from user value and observable behavior, then map to existing
CompanyLens boundaries: API, agent workflow, retrieval, analytics, tool adapters,
evidence validation, persistence, observability, and web UI.

Implementation work MUST follow existing repository patterns, keep changes scoped, and add
tests proportional to risk. Files longer than 250 lines SHOULD be split when cohesive
logic can be extracted safely; if splitting reduces clarity or safety, the reason MUST be
noted in the work summary.

When implementing a GitHub issue, work MUST use a branch named `ID/short-description`, and
commits for issue work MUST reference the issue as `#ID`.

## Governance

This constitution supersedes informal development preferences for Spec Kit artifacts in
this repository. Amendments require an update to this file, a version bump, and review of
dependent Spec Kit templates.

Versioning follows semantic versioning:
- MAJOR for incompatible changes to product or quality gates.
- MINOR for new principles or materially expanded governance.
- PATCH for clarifications that do not change obligations.

Every Spec Kit plan MUST pass the constitution check before implementation tasks are used.
If a plan violates a principle, the violation MUST be documented with the reason and the
simpler rejected alternative.

**Version**: 1.0.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-09
