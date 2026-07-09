# Feature Specification: ML Reranker Service

**Feature Branch**: `61/ml-reranker-service`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Add second-stage ML reranking for retrieved document chunks, packaged as a separate service image so the backend image stays lightweight."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Improve retrieved evidence relevance (Priority: P1)

As a CompanyLens research user, I want narrative document evidence to be ordered by usefulness for my question, so the final answer is grounded in the most relevant filing or PDF passages rather than merely similar text.

**Why this priority**: Evidence quality directly affects answer quality, citation validity, and user trust. This is the core value of reranking.

**Independent Test**: Ask a narrative filing question with more candidate chunks than final evidence slots; verify that the final evidence set prioritizes passages that directly answer the question over generic or weakly related passages.

**Acceptance Scenarios**:

1. **Given** a supported narrative question and enough indexed document candidates, **When** retrieval runs with reranking enabled, **Then** candidates are rescored before final evidence selection.
2. **Given** first-stage retrieval returns both directly relevant and weakly related chunks, **When** reranking completes, **Then** directly relevant chunks receive higher final rank than weakly related chunks.
3. **Given** final answers cite document evidence, **When** reranking changes evidence order, **Then** source lineage, citation IDs, company metadata, period metadata, and source URLs remain intact.

---

### User Story 2 - Keep research usable when reranking is unavailable (Priority: P2)

As a user or operator, I want research runs to continue safely when the reranker is disabled or unavailable, so optional relevance improvement does not make the core product fragile.

**Why this priority**: Reranking is an enhancement to retrieval quality, not a hard dependency for every environment.

**Independent Test**: Run the same retrieval flow with reranking disabled, unavailable, timing out, or returning invalid output; verify the system still produces bounded retrieval results with clear diagnostics.

**Acceptance Scenarios**:

1. **Given** reranking is disabled, **When** retrieval runs, **Then** the system uses first-stage retrieval ordering and records that no reranker was applied.
2. **Given** reranking is enabled but unavailable, **When** graceful degradation is configured, **Then** retrieval continues with first-stage ordering and records the fallback reason.
3. **Given** reranking is enabled but strict failure mode is configured for evaluation, **When** reranking fails, **Then** the run fails at the retrieval boundary with a sanitized internal error.

---

### User Story 3 - Operate reranking without bloating the backend (Priority: P3)

As a maintainer, I want ML reranking dependencies isolated from the main backend runtime, so the API and worker images remain lightweight while local and deployment environments can opt into a heavier model service.

**Why this priority**: The project should gain ML reranking without making every backend build slower, larger, or harder to deploy.

**Independent Test**: Build and run the backend without the reranker service, then run a local environment with the reranker service enabled; verify the backend image does not require model dependencies and reranking can still be enabled.

**Acceptance Scenarios**:

1. **Given** a backend-only environment, **When** the application starts with reranking disabled, **Then** it starts without ML model dependencies.
2. **Given** a local development environment with reranking enabled, **When** retrieval runs, **Then** candidate chunks are scored by the separate reranker service.
3. **Given** the reranker model is changed by configuration, **When** the service restarts, **Then** backend retrieval behavior uses the new model identity in diagnostics without code changes.

---

### User Story 4 - Measure reranking behavior (Priority: P4)

As a developer evaluating retrieval quality, I want reranking diagnostics and benchmark hooks, so I can compare first-stage retrieval against reranked retrieval before enabling it by default.

**Why this priority**: Reranking can improve precision but also introduces latency and model choice tradeoffs. It should be measurable before rollout.

**Independent Test**: Run retrieval tests or a benchmark slice with reranking enabled and disabled; verify that diagnostics report whether reranking ran, how many candidates were scored, model identity, final ranks, and fallback status.

**Acceptance Scenarios**:

1. **Given** reranking is enabled and succeeds, **When** retrieval results are inspected, **Then** each returned result exposes reranker score and rank.
2. **Given** reranking falls back, **When** diagnostics are inspected, **Then** the fallback reason is visible without exposing chunk text or private provider data.
3. **Given** a benchmark compares retrieval modes, **When** reranking is enabled, **Then** the report can distinguish baseline ordering from reranked ordering.

### Edge Cases

- Reranker returns scores for only some candidate IDs.
- Reranker returns duplicate, unknown, non-numeric, or out-of-range score values.
- Reranker response arrives after the configured timeout.
- Reranker service is not running in an environment that selected graceful fallback.
- Candidate chunks contain long text that exceeds model scoring limits.
- First-stage retrieval returns zero candidates.
- Reranking changes ordering but dedupe or diversity rules later remove some high-scoring chunks.
- Diagnostics must not expose raw retrieved text, prompts, credentials, stack traces, or model internals.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support an optional second-stage reranking step for document retrieval candidates before final evidence selection.
- **FR-002**: The system MUST preserve first-stage retrieval as the default behavior when reranking is not explicitly enabled.
- **FR-003**: The system MUST support an ML-backed reranking capability that can be operated outside the main backend runtime.
- **FR-004**: The system MUST rank candidate chunks by reranker relevance score when reranking succeeds.
- **FR-005**: The system MUST preserve all existing source lineage, citation metadata, filters, dedupe behavior, diversity behavior, and evidence identifiers after reranking.
- **FR-006**: The system MUST gracefully fall back to first-stage ordering when reranking is unavailable and fallback mode is configured.
- **FR-007**: The system MUST support a strict failure mode for evaluation environments where reranker failures should fail the retrieval operation.
- **FR-008**: The system MUST record whether reranking was disabled, succeeded, partially succeeded, fell back, or failed.
- **FR-009**: The system MUST record reranker model identity, candidate count, scored count, final reranker rank, final reranker score, and fallback reason when available.
- **FR-010**: The system MUST keep reranker diagnostics privacy-safe by excluding raw chunk text, raw model payloads, credentials, stack traces, and private reasoning.
- **FR-011**: The system MUST validate reranker output before using scores to order candidates.
- **FR-012**: The system MUST keep automated tests independent of downloading or running a real ML model.
- **FR-013**: The system MUST provide a local development path for running retrieval with the external reranker enabled.
- **FR-014**: The system MUST provide a comparison path for measuring retrieval behavior with reranking enabled versus disabled.

### Key Entities *(include if feature involves data)*

- **Rerank Candidate**: A retrieved document chunk submitted for second-stage relevance scoring, identified by an opaque candidate ID and associated with existing source lineage.
- **Rerank Score**: A numeric relevance value assigned to a candidate for a specific user question, where higher values indicate stronger expected usefulness.
- **Rerank Result**: The validated mapping from candidate IDs to rerank scores, model identity, and scoring diagnostics.
- **Rerank Diagnostics**: Privacy-safe metadata describing provider status, candidate counts, scored counts, model identity, latency, fallback reason, and final reranker ranks.
- **Retrieval Result**: The final evidence item returned to the agent after reranking, dedupe, diversity, and top-result selection.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With reranking enabled and a scoring service available, at least one retrieval test demonstrates candidate order changing according to reranker relevance scores.
- **SC-002**: With reranking disabled, existing retrieval behavior remains available and all existing retrieval tests continue to pass.
- **SC-003**: With graceful fallback configured, simulated reranker timeout, invalid response, and service-unavailable cases still return retrieval results with fallback diagnostics.
- **SC-004**: With strict failure mode configured, simulated reranker failure produces a sanitized retrieval failure instead of silently continuing.
- **SC-005**: Reranker diagnostics expose candidate count, scored count, provider status, model identity when available, and per-result reranker rank/score for successful reranks.
- **SC-006**: Backend automated tests for reranker integration run without downloading model weights or requiring ML runtime dependencies.
- **SC-007**: Backend runtime can start with reranking disabled without the external reranker service being available.

## Assumptions

- Reranking applies to document retrieval candidates, not structured financial facts, macro observations, deterministic calculations, or chart datasets.
- The first release keeps reranking disabled by default until quality and latency are evaluated.
- The first release targets CPU-capable local development; GPU acceleration is a later deployment concern.
- Query rewriting and multi-query retrieval are out of scope and should be handled by a follow-up feature after reranking exists.
- Existing retrieval candidate limits remain the primary guardrail for request size and latency.
- Existing citation validation remains the source of truth for final answer safety; reranking improves evidence ordering but does not bypass validation.
