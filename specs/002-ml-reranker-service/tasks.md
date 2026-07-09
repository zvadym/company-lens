# Tasks: ML Reranker Service

**Input**: Design documents from `/specs/002-ml-reranker-service/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests are included because the feature specification defines measurable test outcomes for ordering, fallback, diagnostics, and no-model CI behavior.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on another incomplete task in the same phase.
- **[Story]**: Maps to the user story from `spec.md`.
- Every task includes exact file paths.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the repository layout and dependency boundaries without changing runtime behavior.

- [X] T001 Create the reranker service package scaffold in `reranker/company_lens_reranker/__init__.py`
- [X] T002 [P] Create the reranker service test package scaffold in `reranker/tests/__init__.py`
- [X] T003 [P] Add reranker-service package metadata and ML-only dependencies in `reranker/pyproject.toml`
- [X] T004 [P] Add the standalone reranker container build file in `Dockerfile.reranker`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add shared backend types and configuration that all user stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Add reranker provider settings and validation defaults in `src/company_lens/config.py`
- [X] T006 [P] Add config coverage for provider defaults and invalid values in `tests/test_config.py`
- [X] T007 Define reranker status, diagnostics, request, response, and error types in `src/company_lens/retrieval/rerank.py`
- [X] T008 Extend retrieval response diagnostics fields for reranker status and counts in `src/company_lens/retrieval/schemas.py`
- [X] T009 Thread an optional reranker through adaptive retrieval construction in `src/company_lens/retrieval/adaptive.py`
- [X] T010 Wire configured reranker creation into the SQL research tools path in `src/company_lens/agent/tools.py`
- [X] T011 Wire configured reranker creation into CLI retrieval commands in `src/company_lens/cli.py`

**Checkpoint**: Backend can still run with `noop` reranking and all user-story implementation can build on shared config/types.

---

## Phase 3: User Story 1 - Improve Retrieved Evidence Relevance (Priority: P1) MVP

**Goal**: Rerank document retrieval candidates before final evidence selection while preserving source lineage and citation metadata.

**Independent Test**: Use an injected fake reranker to reorder a known candidate pool in retrieval tests and verify result metadata remains intact.

### Tests for User Story 1

- [X] T012 [P] [US1] Add a fake reranker ordering test in `tests/test_retrieval.py`
- [X] T013 [P] [US1] Add a metadata-preservation assertion for reranked results in `tests/test_retrieval.py`
- [X] T014 [P] [US1] Add adaptive retrieval reranker propagation coverage in `tests/test_adaptive_retrieval.py`

### Implementation for User Story 1

- [X] T015 [US1] Update `_rerank` ordering to record accepted reranker scores and ranks in `src/company_lens/retrieval/service.py`
- [X] T016 [US1] Preserve original retrieval scores, source metadata, dedupe, and diversity behavior after reranking in `src/company_lens/retrieval/service.py`
- [X] T017 [US1] Pass the optional reranker from adaptive retrieval into `RetrievalService` in `src/company_lens/retrieval/adaptive.py`
- [X] T018 [US1] Pass the configured reranker from `SqlResearchTools.retrieve_documents` into `AdaptiveRetrievalService` in `src/company_lens/agent/tools.py`
- [X] T019 [US1] Update retrieval benchmark construction to accept configured reranking in `src/company_lens/retrieval/benchmark.py`

**Checkpoint**: User Story 1 is independently functional through backend tests without the external ML service.

---

## Phase 4: User Story 2 - Keep Research Usable When Reranking Is Unavailable (Priority: P2)

**Goal**: Keep retrieval usable when reranking is disabled or unavailable, while supporting strict failure mode for evaluation.

**Independent Test**: Simulate disabled provider, service timeout, invalid response, partial response, and strict failure in backend tests.

### Tests for User Story 2

- [X] T020 [P] [US2] Add disabled-provider and noop diagnostics tests in `tests/test_retrieval.py`
- [X] T021 [P] [US2] Add HTTP timeout and service-unavailable fallback tests in `tests/test_retrieval.py`
- [X] T022 [P] [US2] Add invalid JSON, missing-score, duplicate-score, and unknown-ID fallback tests in `tests/test_retrieval.py`
- [X] T023 [P] [US2] Add strict fail-closed retrieval error tests in `tests/test_retrieval.py`

### Implementation for User Story 2

- [X] T024 [US2] Implement `HttpReranker` request execution, response validation, and sanitized error classification in `src/company_lens/retrieval/rerank.py`
- [X] T025 [US2] Implement graceful fallback versus strict fail-closed behavior in `src/company_lens/retrieval/rerank.py`
- [X] T026 [US2] Add response-level fallback diagnostics and warning codes in `src/company_lens/retrieval/service.py`
- [X] T027 [US2] Ensure provider exception strings and raw payloads are excluded from retrieval diagnostics in `src/company_lens/retrieval/service.py`
- [X] T028 [US2] Add OpenTelemetry-safe reranker call attributes in `src/company_lens/observability/telemetry.py`

**Checkpoint**: User Story 2 is independently functional with fake HTTP failures and no real model service.

---

## Phase 5: User Story 3 - Operate Reranking Without Bloating The Backend (Priority: P3)

**Goal**: Provide a separate reranker service image and local Docker path without adding ML dependencies to the backend image.

**Independent Test**: Build backend without ML dependencies, run reranker service separately, and verify backend can call it when configured.

### Tests for User Story 3

- [X] T029 [P] [US3] Add reranker service schema validation tests in `reranker/tests/test_schemas.py`
- [X] T030 [P] [US3] Add fake-model scoring and batching tests in `reranker/tests/test_scoring.py`
- [X] T031 [P] [US3] Add ASGI endpoint tests for health, readiness, and rerank responses in `reranker/tests/test_app.py`
- [X] T032 [P] [US3] Add Docker Compose configuration tests for optional reranker service wiring in `tests/test_config.py`

### Implementation for User Story 3

- [X] T033 [US3] Implement reranker request and response schemas in `reranker/company_lens_reranker/schemas.py`
- [X] T034 [US3] Implement lazy CrossEncoder loading and batched scoring in `reranker/company_lens_reranker/scoring.py`
- [X] T035 [US3] Implement `/health`, `/ready`, and `/rerank` endpoints in `reranker/company_lens_reranker/app.py`
- [X] T036 [US3] Configure `Dockerfile.reranker` to install only reranker-service dependencies from `reranker/pyproject.toml`
- [X] T037 [US3] Add optional reranker service, model cache volume, and backend environment variables in `docker-compose.dev.yml`
- [X] T038 [US3] Document local reranker startup and model-cache behavior in `web/README.md`

**Checkpoint**: User Story 3 is independently functional through service unit tests and documented local Docker smoke validation.

---

## Phase 6: User Story 4 - Measure Reranking Behavior (Priority: P4)

**Goal**: Make reranking measurable through diagnostics, benchmark comparison, and privacy checks before enabling it by default.

**Independent Test**: Run retrieval comparison with reranking enabled and disabled and inspect diagnostics for provider status, counts, model identity, score, rank, latency, and fallback reason.

### Tests for User Story 4

- [X] T039 [P] [US4] Add retrieval diagnostics assertions for candidate count, scored count, model identity, score, rank, and fallback reason in `tests/test_retrieval.py`
- [X] T040 [P] [US4] Add benchmark output coverage for baseline versus reranked runs in `tests/test_retrieval.py`
- [X] T041 [P] [US4] Add privacy assertions that diagnostics exclude raw chunk text and raw payloads in `tests/test_retrieval.py`

### Implementation for User Story 4

- [X] T042 [US4] Add reranker provider, status, model, counts, latency, and fallback fields to retrieval diagnostics in `src/company_lens/retrieval/service.py`
- [X] T043 [US4] Add reranking comparison options to retrieval benchmark inputs and reports in `src/company_lens/retrieval/benchmark.py`
- [X] T044 [US4] Add CLI flags or settings pass-through for benchmark reranking comparison in `src/company_lens/cli.py`
- [X] T045 [US4] Update validation instructions for disabled, fake, and real reranker paths in `specs/002-ml-reranker-service/quickstart.md`

**Checkpoint**: User Story 4 is independently functional through diagnostics tests and benchmark comparison output.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, documentation, and graph maintenance across the completed feature.

- [X] T046 [P] Update backend configuration documentation for reranker settings in `README.md`
- [X] T047 [P] Update operations notes for reranker privacy and fallback behavior in `docs/operations.md`
- [X] T048 [P] Add a concise implementation note to the Spec Kit plan if any file over 250 lines was intentionally not split in `specs/002-ml-reranker-service/plan.md`
- [X] T049 Run focused backend and service checks from `specs/002-ml-reranker-service/quickstart.md`
- [X] T050 Run full backend quality gate with `make check` using `Makefile`
- [X] T051 Run `graphify update .` to refresh graph metadata after code changes in `graphify-out/graph.json`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1 and blocks all user stories.
- **Phase 3 US1**: Depends on Phase 2. This is the MVP.
- **Phase 4 US2**: Depends on Phase 2 and can run in parallel with US1 after shared types exist, but final fallback diagnostics should be reconciled with US1 ordering behavior.
- **Phase 5 US3**: Depends on Phase 2 and can run in parallel with US1/US2 because it mainly touches `reranker/`, Docker, and docs.
- **Phase 6 US4**: Depends on US1 and US2 diagnostics behavior; benchmark work can start after Phase 2.
- **Phase 7 Polish**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1 (P1)**: MVP. No dependency on external reranker service; uses injected fake reranker.
- **US2 (P2)**: Builds on the reranker provider contract from Phase 2 and can be tested without real ML runtime.
- **US3 (P3)**: Builds the real external service and Docker path, independent of answer generation.
- **US4 (P4)**: Depends on diagnostics from US1/US2 and benchmark integration from US1.

### Parallel Opportunities

- T002, T003, and T004 can run in parallel after T001.
- T006, T007, and T008 can run in parallel after T005 is understood.
- US1 tests T012, T013, and T014 can be written in parallel.
- US2 tests T020, T021, T022, and T023 can be written in parallel.
- US3 tests T029, T030, T031, and T032 can be written in parallel.
- US4 tests T039, T040, and T041 can be written in parallel.
- Documentation tasks T046, T047, and T048 can run in parallel after implementation stabilizes.

---

## Parallel Example: User Story 1

```bash
Task: "T012 [P] [US1] Add a fake reranker ordering test in tests/test_retrieval.py"
Task: "T013 [P] [US1] Add a metadata-preservation assertion for reranked results in tests/test_retrieval.py"
Task: "T014 [P] [US1] Add adaptive retrieval reranker propagation coverage in tests/test_adaptive_retrieval.py"
```

## Parallel Example: User Story 3

```bash
Task: "T029 [P] [US3] Add reranker service schema validation tests in reranker/tests/test_schemas.py"
Task: "T030 [P] [US3] Add fake-model scoring and batching tests in reranker/tests/test_scoring.py"
Task: "T031 [P] [US3] Add ASGI endpoint tests for health, readiness, and rerank responses in reranker/tests/test_app.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 setup.
2. Complete Phase 2 foundational backend config/types.
3. Complete Phase 3 US1 with fake reranker tests.
4. Stop and validate: `pytest tests/test_retrieval.py tests/test_adaptive_retrieval.py -q`.

### Incremental Delivery

1. US1: reranker injection and ordering with fake scorer.
2. US2: HTTP adapter fallback and strict failure behavior.
3. US3: separate ML service image and Docker path.
4. US4: diagnostics, benchmark comparison, quickstart updates.

### Validation Gates

1. Focused backend retrieval tests after US1 and US2.
2. Reranker service tests after US3.
3. Quickstart smoke validation after US3 and US4.
4. `make check` and `graphify update .` before final implementation handoff.
