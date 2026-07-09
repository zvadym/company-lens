# Tasks: Current Product Baseline

**Input**: Design documents from `/specs/001-current-product-baseline/`

**Prerequisites**: plan.md, spec.md

**Tests**: These are backlog validation and documentation tasks. Add implementation tests only when a task uncovers missing or stale coverage.

**Organization**: Tasks are grouped by user story so each area can be validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make Spec Kit usable in the repository and anchor the baseline to existing docs.

- [ ] T001 Verify Spec Kit installation metadata in `.specify/init-options.json`
- [ ] T002 Review CompanyLens constitution gates in `.specify/memory/constitution.md`
- [ ] T003 [P] Cross-link baseline artifacts from `README.md` or `docs/operations.md` if the team wants this visible in normal project navigation

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Confirm that the baseline backlog describes real, current behavior and not desired future behavior.

- [ ] T004 Review `README.md` capabilities against `specs/001-current-product-baseline/spec.md`
- [ ] T005 [P] Review API/SSE behavior against `docs/research-api.md`
- [ ] T006 [P] Review financial metrics behavior against `docs/financial-metrics.md`
- [ ] T007 [P] Review macro analytics behavior against `docs/macro-analytics.md`
- [ ] T008 [P] Review persistent session behavior against `docs/architecture/adr-0005-persistent-research-sessions.md`
- [ ] T009 Update `specs/001-current-product-baseline/spec.md` if any reviewed behavior is stale or overstated

**Checkpoint**: Baseline backlog reflects current product behavior.

---

## Phase 3: User Story 1 - Answer grounded company research questions (Priority: P1) MVP

**Goal**: Validate the core research answer capability across narrative, financial, and hybrid paths.

**Independent Test**: Run or review tests for narrative retrieval, financial facts, macro series, calculations, chart generation, evidence merge, and citation validation.

- [ ] T010 [P] [US1] Review route planning coverage in `tests/agent_workflow/test_routes_core.py`
- [ ] T011 [P] [US1] Review financial source and fallback coverage in `tests/agent_workflow/test_financial_fallbacks.py`
- [ ] T012 [P] [US1] Review macro source and chart coverage in `tests/agent_workflow/test_chart_generation.py`
- [ ] T013 [P] [US1] Review citation validation coverage in `tests/test_evidence_validation.py`
- [ ] T014 [US1] Record any unsupported answer path in `specs/001-current-product-baseline/tasks.md` or create a dedicated follow-up under `specs/`

**Checkpoint**: Core answer paths are represented in docs and tests.

---

## Phase 4: User Story 2 - Inspect research run progress and results (Priority: P2)

**Goal**: Validate API, SSE, source preview, trace, and UI presentation behavior.

**Independent Test**: Start or inspect a research run and verify lifecycle, event replay, final result, source previews, and web presentation.

- [ ] T015 [P] [US2] Review API run lifecycle coverage in `tests/test_research_api.py`
- [ ] T016 [P] [US2] Review PostgreSQL research API coverage in `tests/test_research_api_postgres.py`
- [ ] T017 [P] [US2] Review worker behavior in `tests/test_research_worker.py`
- [ ] T018 [P] [US2] Review web event handling in `web/src/research/events.test.ts`
- [ ] T019 [P] [US2] Review source panel presentation in `web/src/components/SourcesPanel.test.tsx`
- [ ] T020 [US2] Record any privacy or trace contract gap in `specs/001-current-product-baseline/tasks.md` or create a dedicated follow-up under `specs/`

**Checkpoint**: Run inspection behavior is documented and covered.

---

## Phase 5: User Story 3 - Continue and reuse research context (Priority: P3)

**Goal**: Validate follow-up resolution, session memory, source cache reuse, and explicit override behavior.

**Independent Test**: Run or review tests where a follow-up inherits prior companies and where explicit current entities override session context.

- [ ] T021 [P] [US3] Review follow-up company context coverage in `tests/agent_workflow/test_followup_company_sets.py`
- [ ] T022 [P] [US3] Review ambiguity and memory coverage in `tests/agent_workflow/test_ambiguity_and_memory.py`
- [ ] T023 [P] [US3] Review replay variants in `tests/agent_workflow/test_replay_variants.py`
- [ ] T024 [P] [US3] Review persistent agent session coverage in `tests/test_agent_persistence.py`
- [ ] T025 [US3] Record any unsafe inheritance or cache reuse behavior in `specs/001-current-product-baseline/tasks.md` or create a dedicated follow-up under `specs/`

**Checkpoint**: Follow-up behavior is safe, bounded, and represented in baseline docs.

---

## Phase 6: User Story 4 - Maintain ingestion and analytics readiness (Priority: P4)

**Goal**: Validate data readiness workflows for SEC filings, SEC Company Facts, PDFs, FRED, calculations, and chart datasets.

**Independent Test**: In the Docker dev stack, ingest/query representative SEC facts and FRED series, process/index documents, and verify deterministic calculation outputs.

- [ ] T026 [P] [US4] Review SEC ingestion coverage in `tests/test_sec_ingestion.py`
- [ ] T027 [P] [US4] Review company facts coverage in `tests/test_company_facts.py`
- [ ] T028 [P] [US4] Review PDF ingestion coverage in `tests/test_pdf_ingestion.py`
- [ ] T029 [P] [US4] Review FRED coverage in `tests/test_fred.py`
- [ ] T030 [P] [US4] Review analytics coverage in `tests/test_analytics.py`
- [ ] T031 [US4] Record any ingestion readiness gap in `specs/001-current-product-baseline/tasks.md` or create a dedicated follow-up under `specs/`

**Checkpoint**: Data readiness workflows have visible backlog owners and coverage checks.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Turn the baseline into a useful project planning asset.

- [ ] T032 [P] Add links from `specs/001-current-product-baseline/spec.md` to relevant ADRs if long-term navigation becomes important
- [ ] T033 [P] Decide whether to convert selected tasks to GitHub issues with `$speckit-taskstoissues`
- [ ] T034 Run `make check` after any follow-up changes under `src/company_lens/` or `tests/`
- [ ] T035 Run `pnpm --dir web lint`, `pnpm --dir web typecheck`, `pnpm --dir web test`, and `pnpm --dir web build` after any follow-up changes under `web/src/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks story validation.
- **User Stories (Phase 3-6)**: Depend on Foundational completion and can run in parallel.
- **Polish (Phase 7)**: Depends on whichever story validations the team chooses to complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational; no dependency on other stories.
- **User Story 2 (P2)**: Can start after Foundational; no dependency on other stories.
- **User Story 3 (P3)**: Can start after Foundational; benefits from US1 context but can be reviewed independently.
- **User Story 4 (P4)**: Can start after Foundational; feeds US1 quality but can be reviewed independently.

### Parallel Opportunities

- T005-T008 can run in parallel.
- US1 review tasks T010-T013 can run in parallel.
- US2 review tasks T015-T019 can run in parallel.
- US3 review tasks T021-T024 can run in parallel.
- US4 review tasks T026-T030 can run in parallel.

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001-T009.
2. Complete T010-T014.
3. Decide whether any US1 gaps deserve standalone Spec Kit specs or GitHub issues.

### Incremental Delivery

1. Validate P1 core answer behavior.
2. Validate P2 API/SSE/UI inspection behavior.
3. Validate P3 follow-up/session behavior.
4. Validate P4 ingestion/analytics readiness.
5. Convert selected gaps into issues or dedicated future specs.
