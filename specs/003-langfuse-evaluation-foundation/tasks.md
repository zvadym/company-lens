# Tasks: Langfuse Evaluation Foundation

**Input**: Design documents from `specs/003-langfuse-evaluation-foundation/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`,
`quickstart.md`

**Tests**: Required. The specification explicitly defines independent tests, deterministic
evaluation behavior, citation validation, failure classification, and privacy boundaries. Write
the listed tests first and confirm they fail for the intended reason before implementation.

**Organization**: Tasks are grouped by user story. Shared typed contracts, module splits, Langfuse
mapping, and synchronization primitives are foundational because the P1 manual run and P2 explicit
sync workflow both depend on them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel after its phase prerequisites are satisfied because it primarily
  touches different files.
- **[Story]**: Maps the task to a user story from `spec.md`.
- Every task includes exact repository paths.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare dependency, artifact, and test-support boundaries without changing behavior.

- [ ] T001 Raise the supported Langfuse SDK floor to `>=4.9.1,<5` in `pyproject.toml` and confirm the resolved SDK exposes versioned dataset retrieval and experiment APIs
- [ ] T002 [P] Exclude generated evaluation run artifacts under `artifacts/evaluations/` in `.gitignore`
- [ ] T003 [P] Create reusable typed Langfuse dataset, score-config, experiment, and failure fakes in `tests/evals/__init__.py` and `tests/evals/fakes_langfuse.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish typed contracts, preserve existing deterministic behavior during module
splits, and implement fail-closed Langfuse preflight primitives shared by all stories.

**Critical**: No user story implementation starts until this phase is green.

### Foundational Tests

- [ ] T004 [P] Add failing tests for citation-mode defaults, citation-scenario validation, source-path/hash metadata, and backward-compatible golden loading in `tests/test_golden_dataset.py`
- [ ] T005 [P] Add failing tests for execution/run state invariants, sanitized infrastructure outcomes, citation observations, manifests, and `passed|failed|not_evaluated` gate states in `tests/evals/test_models.py`
- [ ] T006 [P] Add failing tests for score-contract uniqueness, type/range/category rules, applicability, 35-character names, canonical hashing, and incompatible semantic changes in `tests/evals/test_score_contract.py`
- [ ] T007 [P] Add failing tests for deterministic UUIDv5 item/score IDs, canonical Langfuse payloads, active/stale mapping, and content hashes in `tests/evals/test_langfuse_mapping.py`
- [ ] T008 [P] Add failing adapter tests for dataset create/upsert/archive, score-config reconciliation, exact-version readback, partial sync, concurrent mismatch, and zero-provider-call preflight failure in `tests/evals/test_langfuse_sync.py`

### Foundational Implementation

- [ ] T009 Extend `GoldenDatasetCase` with effective citation mode/scenario, source-aware loading, canonical hashing, and coverage-summary fields in `src/company_lens/evals/golden.py`
- [ ] T010 Extract observed, citation, score, report, snapshot, manifest, dataset-run, and execution Pydantic models from `src/company_lens/evals/deterministic.py` into `src/company_lens/evals/models.py`
- [ ] T011 Implement repository-authored score-contract models/loaders in `src/company_lens/evals/score_contract.py` and create all item/run definitions from `contracts/langfuse-mapping.md` in `evals/score-contracts/foundation.v1.yaml`
- [ ] T012 [P] Rename regression-gate types/functions to evaluation-gate terminology and extract threshold/budget logic into `src/company_lens/evals/gates.py` while preserving the reviewed shapes of `evals/gates/eval-fast.v1.yaml` and `evals/gates/eval-full.v1.yaml`
- [ ] T013 [P] Extract pure per-case checks and aggregate/category metric calculations from `src/company_lens/evals/deterministic.py` into `src/company_lens/evals/checks.py` without changing existing results
- [ ] T014 Extract deterministic Markdown formatting into `src/company_lens/evals/reporting.py` and reduce `src/company_lens/evals/deterministic.py` to a compatibility facade with stable public re-exports
- [ ] T015 [P] Add a failing privacy/configuration test for retrieving the configured Langfuse client without exposing credentials or raw configuration errors in `tests/test_observability_security.py`
- [ ] T016 Expose a typed current-Langfuse-client accessor and sanitized missing-client error from `src/company_lens/observability/telemetry.py` for adapter dependency injection
- [ ] T017 Implement deterministic repository-to-Langfuse item mapping, canonical serialization, UUIDv5 identities, and hashes in `src/company_lens/evals/langfuse_mapping.py`
- [ ] T018 Implement score-config lookup/create/compatibility checks and deterministic full-payload score publication in `src/company_lens/evals/langfuse_scores.py`
- [ ] T019 Implement all-datasets-first synchronization, stale-item archival, exact timestamp pinning/readback, and snapshot verification in `src/company_lens/evals/langfuse_sync.py`
- [ ] T020 Extract existing evaluation parser registration/handlers from `src/company_lens/cli.py` into `src/company_lens/evals/cli.py`, preserving `validate-golden-dataset`, `run-golden-agent`, and `evaluate-golden-results` behavior and updating `tests/test_agent_cli.py`
- [ ] T021 Run the foundational suite in `tests/test_golden_dataset.py`, `tests/test_deterministic_evals.py`, `tests/evals/test_models.py`, `tests/evals/test_score_contract.py`, `tests/evals/test_langfuse_mapping.py`, `tests/evals/test_langfuse_sync.py`, and `tests/test_observability_security.py`

**Checkpoint**: Existing deterministic commands remain green; exact repository/Langfuse preflight
and score contracts are usable by US1 and US2 without provider-backed calls.

---

## Phase 3: User Story 1 - Run Manual Evaluation Visible in Langfuse (Priority: P1)

**Goal**: Run one manual umbrella execution, create one pinned Langfuse experiment per selected
dataset, publish deterministic/citation scores, preserve artifacts, and return an unambiguous
quality or infrastructure result.

**Independent Test**: Run `run-evaluation` against one fake-backed selected dataset and verify one
terminal record per case, applicable item scores, trusted aggregate/gate scores, JSON/Markdown
artifacts, and a Langfuse run URL. Repeat with a behavior failure and an infrastructure failure to
verify exit codes `1` and `2` and aggregate suppression.

### Tests for User Story 1

- [ ] T022 [P] [US1] Add failing tests for privacy-safe `AgentState` projection, answer presence, citation validity/reason codes, unknown evidence IDs, and not-applicable citation omission in `tests/evals/test_agent_observation.py`
- [ ] T023 [P] [US1] Add failing tests for isolated case sessions, multi-turn reuse within one case, captured missing-answer behavior failure, and sanitized provider/runner infrastructure outcomes in `tests/test_golden_agent_runner.py`
- [ ] T024 [P] [US1] Add failing tests for pinned `DatasetClient.run_experiment`, applicable score-config IDs, deterministic score IDs, dropped-item/evaluator detection, dataset-run linkage, partial-run `not_evaluated`, and flush behavior in `tests/evals/test_langfuse_experiment.py`
- [ ] T025 [P] [US1] Add failing tests for all-preflights-before-agent, one run per dataset, shared execution ID/manifest, sequential datasets, completed/partial/errored transitions, gate derivation, and atomic artifacts in `tests/evals/test_evaluation_orchestrator.py`
- [ ] T026 [P] [US1] Add failing CLI contract tests for repeatable datasets, per-dataset max cases, policy/manifest metadata, output paths, sanitized errors, and exit codes `0|1|2` in `tests/evals/test_run_evaluation_cli.py`

### Implementation for User Story 1

- [ ] T027 [US1] Implement the privacy-safe `AgentState` to `CaseObservation` projection and citation classification in `src/company_lens/evals/observation.py`
- [ ] T028 [US1] Refactor case selection/execution in `src/company_lens/evals/agent_runner.py` to use `observation.py`, preserve isolated durable sessions, collect operational metrics, and capture sanitized terminal outcomes without dropping cases
- [ ] T029 [P] [US1] Implement pinned dataset experiment execution, item evaluator adaptation, post-run cardinality/linkage/score verification, and trusted run-score publication in `src/company_lens/evals/langfuse_experiment.py`
- [ ] T030 [P] [US1] Implement atomic privacy-safe `evaluation-execution.json` and `evaluation-summary.md` rendering, forbidden-content guards, and bounded failure reasons in `src/company_lens/evals/reporting.py`
- [ ] T031 [US1] Implement the multi-dataset preflight/run/finalize state machine, immutable manifest construction, quality-vs-infrastructure classification, and exit-code mapping in `src/company_lens/evals/orchestrator.py`
- [ ] T032 [US1] Add the `run-evaluation` parser/handler from `contracts/evaluation-cli.md` to `src/company_lens/evals/cli.py` and wire dispatch through `src/company_lens/cli.py`
- [ ] T033 [US1] Publish the stable execution/orchestration surface and compatibility exports from `src/company_lens/evals/__init__.py`
- [ ] T034 [US1] Run the US1 focused suite in `tests/evals/test_agent_observation.py`, `tests/test_golden_agent_runner.py`, `tests/evals/test_langfuse_experiment.py`, `tests/evals/test_evaluation_orchestrator.py`, and `tests/evals/test_run_evaluation_cli.py`

**Checkpoint**: The P1 MVP is independently runnable and visible in Langfuse/local artifacts, with
no PR comment requirement and no LLM-as-judge behavior.

---

## Phase 4: User Story 2 - Sync Repo Golden Cases to Langfuse (Priority: P2)

**Goal**: Give maintainers an explicit dry-run/sync command that keeps repository YAML authoritative,
upserts stable items, archives stale items, reconciles score configs, and verifies exact snapshots.

**Independent Test**: Run sync twice against a fake Langfuse project and verify the same item IDs
exist once, unchanged cases do not duplicate, stale cases become archived, exact hashes/version
timestamps are reported, and an injected mismatch exits `2` without provider calls.

### Tests for User Story 2

- [ ] T035 [P] [US2] Add failing CLI tests for default/repeated datasets, dry-run no-write behavior, verified sync JSON, stale reporting, output-file handling, and infrastructure exit code `2` in `tests/evals/test_sync_evaluation_cli.py`

### Implementation for User Story 2

- [ ] T036 [US2] Add the `sync-evaluation-datasets` parser/handler from `contracts/evaluation-cli.md` to `src/company_lens/evals/cli.py` using the foundational sync and score-config services
- [ ] T037 [US2] Document deterministic IDs, active/archive semantics, dry-run, exact-version verification, and repository ownership in `evals/datasets/golden/README.md`
- [ ] T038 [US2] Run US2 idempotency and mismatch validation in `tests/evals/test_langfuse_sync.py` and `tests/evals/test_sync_evaluation_cli.py`

**Checkpoint**: Dataset synchronization is independently usable and testable without running the
agent or depending on US3/US4.

---

## Phase 5: User Story 3 - Review Manual Evaluation from a PR (Priority: P3)

**Goal**: Optionally attach one canonical, privacy-safe evaluation summary to the exact PR commit
while preserving artifacts/runs and surfacing reporting failures separately.

**Independent Test**: Against a fake GitHub API, report a completed execution to a matching PR head,
rerun it, and verify one bot-authored marker comment is updated. Verify mismatched SHA, duplicate
markers, permission failure, and API failure return reporting infrastructure status without altering
the evaluation artifact or gate result.

### Tests for User Story 3

- [ ] T039 [P] [US3] Add failing tests for PR repository/head-SHA validation, canonical marker lookup/create/update, duplicate detection, sanitized body generation, and API/permission failures in `tests/evals/test_github_reporting.py`
- [ ] T040 [P] [US3] Add a failing workflow contract test for `workflow_dispatch` inputs, Testing secrets, permissions, fixed dataset allowlist, captured exit code, unconditional artifact upload, optional report step, and final status propagation in `tests/evals/test_evaluation_workflow.py`

### Implementation for User Story 3

- [ ] T041 [US3] Implement typed GitHub PR lookup/comment reporting with the stable marker and privacy-safe errors in `src/company_lens/evals/github_reporting.py`
- [ ] T042 [US3] Add a `report-evaluation-pr` handler that reads the existing JSON/Markdown artifacts without mutating their gate result in `src/company_lens/evals/cli.py`
- [ ] T043 [US3] Replace free-form dataset input with `all|core|follow_up`, add optional PR number, run the orchestrator, upload artifacts, report the matching PR, and propagate exit codes in `.github/workflows/eval-full.yml`
- [ ] T044 [US3] Run the US3 focused suite in `tests/evals/test_github_reporting.py` and `tests/evals/test_evaluation_workflow.py`

**Checkpoint**: A manual workflow run can produce exactly one trustworthy PR summary, while PR
reporting remains optional and non-required by feature 003.

---

## Phase 6: User Story 4 - Expand Critical Golden Coverage (Priority: P4)

**Goal**: Expand the reviewed repository source of truth from 11 to 18 cases with at least two cases
in every category and four citation scenarios, without embedding Langfuse-specific truth in YAML.

**Independent Test**: Validate both golden datasets and assert 18-25 total cases, every category
count at least two, valid/missing-attempt/unknown-evidence-attempt/semantic-mismatch-attempt coverage,
and framework-neutral expected behavior.

### Tests for User Story 4

- [ ] T045 [US4] Replace starter-count assertions with failing foundation coverage, citation-mode/scenario, category-minimum, and framework-neutrality tests in `tests/test_golden_dataset.py`

### Implementation for User Story 4

- [ ] T046 [US4] Annotate the existing seven core cases and four follow-up cases with reviewed effective citation modes/scenarios in `evals/datasets/golden/core.v1.yaml` and `evals/datasets/golden/follow_up.v1.yaml`
- [ ] T047 [US4] Add seven reviewed core cases covering the second case in each non-follow-up category and all missing citation scenarios within the 18-case total in `evals/datasets/golden/core.v1.yaml`
- [ ] T048 [US4] Document category and citation-scenario authoring rules plus the 18-25 coverage invariant in `evals/datasets/golden/README.md`
- [ ] T049 [US4] Run golden validation and deterministic regression tests in `tests/test_golden_dataset.py`, `tests/test_deterministic_evals.py`, and `tests/test_golden_agent_runner.py`

**Checkpoint**: The initial foundation dataset has balanced critical coverage and remains the sole
reviewed source of truth for synchronized Langfuse items.

---

## Phase 7: Polish and Cross-Cutting Validation

**Purpose**: Finish operational documentation, contract/security checks, graph freshness, and
end-to-end validation across all selected stories.

- [ ] T050 [P] Add the manual evaluation, required environment values, Langfuse dataset/run/score inspection, exit-code triage, and privacy guidance to `docs/operations.md`
- [ ] T051 [P] Add forbidden-content scans across JSON, Markdown, score comments, CLI errors, and PR bodies in `tests/evals/test_evaluation_reporting.py` and `tests/test_observability_security.py`
- [ ] T052 [P] Validate generated execution artifacts and repository score contracts against `specs/003-langfuse-evaluation-foundation/contracts/evaluation-execution.schema.json` and `specs/003-langfuse-evaluation-foundation/contracts/score-contract.schema.json` in `tests/evals/test_contract_schemas.py`
- [ ] T053 Execute the non-provider setup, golden validation, sync dry-run, exact-sync idempotency, and focused failure scenarios from `specs/003-langfuse-evaluation-foundation/quickstart.md`, correcting command/document drift in that file
- [ ] T054 Run `graphify update .` and review generated impact for the evaluation modules recorded in `graphify-out/graph.json`
- [ ] T055 Run the full repository quality gate with `make check` and resolve all failures in the files changed by feature 003
- [ ] T056 Run `.github/workflows/eval-full.yml` manually against a Testing PR/ref, verify artifacts plus Langfuse dataset-run links and one canonical PR comment, and record any environment-only limitation in `specs/003-langfuse-evaluation-foundation/quickstart.md`

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 1 Setup**: Starts immediately.
- **Phase 2 Foundational**: Depends on Phase 1 and blocks all user stories.
- **US1 (Phase 3)**: Depends on Phase 2. This is the MVP.
- **US2 (Phase 4)**: Depends on Phase 2 and may run in parallel with US1 because it exposes the
  already-foundational sync service through an independent command.
- **US3 (Phase 5)**: Depends on US1 artifacts/reporting and can start after T030-T032 are stable.
- **US4 (Phase 6)**: Depends on T009 and may run in parallel with US1/US2; it should complete before
  the final full workflow validation.
- **Polish (Phase 7)**: Depends on all stories selected for delivery.

### Foundational Internal Order

1. Write T004-T008 and T015 tests.
2. Implement golden/models/score contracts in T009-T011.
3. Implement gates/checks in parallel through T012-T013.
4. Restore the deterministic facade/reporting in T014.
5. Complete client/mapping/scores/sync in T016-T019.
6. Extract CLI handlers in T020 and pass T021.

### User Story Dependencies

- **US1**: No dependency on another user story after Phase 2.
- **US2**: No dependency on another user story after Phase 2.
- **US3**: Consumes US1 execution JSON/Markdown artifacts; it does not alter their gate result.
- **US4**: No dependency on another story after the foundational golden schema, but final live
  validation uses its expanded cases.

### Requirement Coverage

| Requirements | Primary tasks |
|---|---|
| FR-001-FR-005, FR-026, FR-028, FR-030 | T004, T007-T009, T017-T019, T035-T038 |
| FR-006-FR-014, FR-018-FR-021, FR-027 | T022-T034 |
| FR-015, FR-022-FR-024, FR-029 | T045-T049 |
| FR-016 | T011, T024, T051-T052 |
| FR-017 | T022-T030, T039-T044, T050-T052 |
| FR-025 | T022-T031 |
| FR-031 | T006, T010-T011, T018, T024, T052 |
| SC-001-SC-014 | T021, T034, T038, T044, T049, T051-T056 |

---

## Parallel Opportunities

- T002 and T003 can run in parallel after T001 is understood.
- Foundational tests T004-T008 and T015 touch separate files and can be written in parallel.
- After T010, gate extraction T012 and check extraction T013 can run in parallel.
- US1 tests T022-T026 can be written in parallel against the contracts.
- After T027/T028 establish the observation shape, T029 experiment integration and T030 artifact
  reporting can proceed in parallel before T031 orchestration.
- US2 can proceed in parallel with US1 after Phase 2.
- US4 can proceed in parallel with US1/US2 after T009.
- US3 tests T039 and T040 can run in parallel.
- Polish documentation/security/schema tasks T050-T052 can run in parallel.

## Parallel Example: User Story 1

```text
Task T022: Write AgentState projection tests in tests/evals/test_agent_observation.py
Task T023: Write runner terminal-outcome tests in tests/test_golden_agent_runner.py
Task T024: Write Langfuse experiment adapter tests in tests/evals/test_langfuse_experiment.py
Task T025: Write orchestration state-machine tests in tests/evals/test_evaluation_orchestrator.py
Task T026: Write run-evaluation CLI tests in tests/evals/test_run_evaluation_cli.py

After observation contracts are stable:
Task T029: Implement Langfuse experiment integration in src/company_lens/evals/langfuse_experiment.py
Task T030: Implement execution artifact reporting in src/company_lens/evals/reporting.py
```

## Parallel Example: User Stories 2 and 4

```text
Task T035-T038: Implement and validate the explicit sync command (US2)
Task T045-T049: Expand and validate repository golden coverage (US4)
```

---

## Implementation Strategy

### MVP First: User Story 1

1. Complete Setup and Foundational phases.
2. Complete US1 through T034.
3. Stop and validate one dataset with fakes and a bounded live smoke run.
4. Confirm Langfuse run visibility, deterministic scores, artifacts, and exit semantics.

This MVP already includes internal exact synchronization because a trustworthy experiment cannot run
without it. It does not yet expose the standalone sync command, PR comment, or expanded coverage.

### Incremental Delivery

1. **Foundation + US1**: Manual Langfuse experiment MVP.
2. **US2**: Maintainer-facing explicit sync/dry-run workflow.
3. **US3**: Optional canonical PR reporting.
4. **US4**: Balanced 18-case critical coverage.
5. **Polish**: Security, schemas, operations, full manual workflow validation.

### Commit and Validation Discipline

- Keep tests red before the implementation task they specify.
- Commit after each task or cohesive task group; do not mix unrelated refactors.
- Run focused tests at every story checkpoint and `make check` before every commit.
- After code modifications, run `graphify update .` before final delivery.
- Do not add LLM-as-judge, annotation queues, calibration, or production monitoring in feature 003.
