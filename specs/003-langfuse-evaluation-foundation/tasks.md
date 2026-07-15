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

- [X] T001 Raise the supported Langfuse SDK floor to `>=4.9.1,<5` in `pyproject.toml` and confirm the resolved SDK exposes versioned dataset retrieval and experiment APIs
- [X] T002 [P] Exclude generated evaluation run artifacts under `artifacts/evaluations/` in `.gitignore`
- [X] T003 [P] Create reusable typed Langfuse project-identity, dataset, score-config, experiment, mutation-counter, and failure fakes in `tests/evals/__init__.py` and `tests/evals/fakes_langfuse.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish typed contracts, preserve existing deterministic behavior during module
splits, and implement fail-closed Langfuse preflight primitives shared by all stories.

**Critical**: No user story implementation starts until this phase is green.

### Foundational Tests

- [X] T004 [P] Add failing tests for citation-mode defaults, citation-scenario validation, source-path/hash metadata, and backward-compatible golden loading in `tests/test_golden_dataset.py`
- [X] T005 [P] Add failing tests for execution/run state invariants, sanitized infrastructure outcomes, citation observations, strict normal/replay manifests, the full journal phase/status/gate/reporting matrix, dataset-scoped terminal case identities, monotonic recovery journals, and `pending|passed|failed|not_evaluated` gate states in `tests/evals/test_models.py`
- [X] T006 [P] Add failing tests for score-contract uniqueness, type/range/category rules, applicability, 35-character names, canonical hashing, and incompatible semantic changes in `tests/evals/test_score_contract.py`
- [X] T007 [P] Add failing tests for deterministic UUIDv5 item/score IDs, canonical Langfuse payloads, active/stale mapping, and content hashes in `tests/evals/test_langfuse_mapping.py`
- [X] T008 [P] Add failing adapter tests for key-associated project lookup/mismatch before mutation, dataset create/upsert/archive, score-config reconciliation, exact-version readback, read-only replay, partial sync, concurrent mismatch, mutation counts, and zero-provider-call preflight failure in `tests/evals/test_langfuse_sync.py`

### Foundational Implementation

- [X] T009 Extend `GoldenDatasetCase` with effective citation mode/scenario, source-aware loading, canonical hashing, and coverage-summary fields in `src/company_lens/evals/golden.py`
- [X] T010 Extract observed, citation, score, report, project-identity, snapshot, normal/replay manifest, recovery-journal, dataset-run, and execution Pydantic models from `src/company_lens/evals/deterministic.py` into `src/company_lens/evals/models.py`
- [X] T011 Implement repository-authored score-contract models/loaders in `src/company_lens/evals/score_contract.py` and create all item/run definitions from `contracts/langfuse-mapping.md` in `evals/score-contracts/foundation.v1.yaml`
- [X] T012 [P] Rename regression-gate types/functions to evaluation-gate terminology and extract threshold/budget logic into `src/company_lens/evals/gates.py` while preserving the reviewed shapes of `evals/gates/eval-fast.v1.yaml` and `evals/gates/eval-full.v1.yaml`
- [X] T013 [P] Extract pure per-case checks and aggregate/category metric calculations from `src/company_lens/evals/deterministic.py` into `src/company_lens/evals/checks.py` without changing existing results
- [X] T014 Extract deterministic Markdown formatting into `src/company_lens/evals/reporting.py` and reduce `src/company_lens/evals/deterministic.py` to a compatibility facade with stable public re-exports
- [X] T015 [P] Add failing settings/client tests for required evaluation project ID, project-scoped identity lookup, shared client lifecycle, and sanitized missing/mismatched-client errors in `tests/test_config.py` and `tests/test_observability_security.py`
- [X] T016 Extract typed Langfuse client construction, lifecycle, current-client access, and public project-identity verification from `src/company_lens/observability/telemetry.py` into `src/company_lens/observability/langfuse_client.py`; add `COMPANY_LENS_LANGFUSE_PROJECT_ID` wiring in `src/company_lens/config.py`, `.env.example`, and `docker-compose.yml`
- [X] T017 Implement deterministic repository-to-Langfuse item mapping, canonical serialization, UUIDv5 identities, and hashes in `src/company_lens/evals/langfuse_mapping.py`
- [X] T018 Implement score-config lookup/create/compatibility checks and deterministic full-payload score publication in `src/company_lens/evals/langfuse_scores.py`
- [X] T019 Implement project-identity-first synchronization, stale-item archival, exact timestamp pinning/readback, snapshot verification, and mutation-free recorded-snapshot replay loading in `src/company_lens/evals/langfuse_sync.py`
- [X] T020 Extract existing evaluation parser registration/handlers from `src/company_lens/cli.py` into `src/company_lens/evals/cli.py`, preserving `validate-golden-dataset`, `run-golden-agent`, and `evaluate-golden-results` behavior and updating `tests/test_agent_cli.py`
- [X] T021 Run the foundational suite in `tests/test_golden_dataset.py`, `tests/test_deterministic_evals.py`, `tests/evals/test_models.py`, `tests/evals/test_score_contract.py`, `tests/evals/test_langfuse_mapping.py`, `tests/evals/test_langfuse_sync.py`, and `tests/test_observability_security.py`

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

- [X] T022 [P] [US1] Add failing tests for privacy-safe `AgentState` projection, answer presence, citation validity/reason codes, unknown evidence IDs, and not-applicable citation omission in `tests/evals/test_agent_observation.py`
- [X] T023 [P] [US1] Add failing tests for isolated case sessions, multi-turn reuse within one case, captured missing-answer behavior failure, sanitized provider/runner infrastructure outcomes, and a single full-conversation replay in a fresh session after exhausted provider retries in `tests/test_golden_agent_runner.py` and `tests/evals/test_agent_runner_infrastructure.py`
- [X] T024 [P] [US1] Add failing tests for pinned `DatasetClient.run_experiment`, applicable score-config IDs, deterministic score IDs, dropped-item/evaluator detection, dataset-run linkage, partial-run `not_evaluated`, and flush behavior in `tests/evals/test_langfuse_experiment.py`
- [X] T025 [P] [US1] Add failing tests for project/all-dataset preflights before agent calls, target-aware preflight-failure transitions to `reporting/pending` or `terminal/not_requested`, one run per dataset, shared execution ID/manifest, read-only replay with a new linked execution, sequential datasets, every injected journal transition/interruption, recovery materialization, completed/partial/errored transitions, gate derivation, and atomic artifacts in `tests/evals/test_evaluation_orchestrator.py`
- [X] T026 [P] [US1] Add failing CLI contract tests for normal/replay mutual exclusion, immutable replay overrides, repeatable datasets, per-dataset max cases, paired optional repository/PR reporting target, policy/manifest metadata, `recover-evaluation`, output paths, sanitized errors, signals, and exit codes `0|1|2` in `tests/evals/test_run_evaluation_cli.py`

### Implementation for User Story 1

- [X] T027 [US1] Implement the privacy-safe `AgentState` to `CaseObservation` projection and citation classification in `src/company_lens/evals/observation.py`
- [X] T028 [US1] Refactor case selection/execution in `src/company_lens/evals/agent_runner.py` to use `observation.py`, preserve isolated durable sessions, collect operational metrics, capture sanitized terminal outcomes without dropping cases, and replay the complete case at most once in a fresh session only after exhausted provider-infrastructure retries
- [X] T029 [P] [US1] Implement pinned dataset experiment execution, item evaluator adaptation, post-run cardinality/linkage/score verification, and trusted run-score publication in `src/company_lens/evals/langfuse_experiment.py`
- [X] T030 [P] [US1] Implement validated sequence-monotonic atomic `evaluation-journal.json` checkpoints with independent reporting state/failure codes, dataset-scoped terminal case identities, target-aware recovery transitions, recovery materialization, privacy-safe `evaluation-execution.json`/`evaluation-summary.md` rendering, forbidden-content guards, and bounded failure reasons in `src/company_lens/evals/reporting.py`
- [X] T031 [US1] Implement project-aware normal preflight, immutable manifest construction, mutation-free manifest replay with a new linked execution, optional PR reporting-intent initialization, multi-dataset run/finalize state transitions, journal checkpoints, target-aware graceful interruption, quality-vs-infrastructure classification, and exit-code mapping in `src/company_lens/evals/orchestrator.py`
- [X] T032 [US1] Add the normal/replay `run-evaluation` and `recover-evaluation` parsers/handlers from `contracts/evaluation-cli.md` to `src/company_lens/evals/cli.py` and wire dispatch plus `SIGINT`/`SIGTERM` handling through `src/company_lens/cli.py`
- [X] T033 [US1] Publish the stable execution/orchestration surface and compatibility exports from `src/company_lens/evals/__init__.py`
- [X] T034 [US1] Run the US1 focused suite in `tests/evals/test_agent_observation.py`, `tests/test_golden_agent_runner.py`, `tests/evals/test_langfuse_experiment.py`, `tests/evals/test_evaluation_orchestrator.py`, and `tests/evals/test_run_evaluation_cli.py`

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

- [X] T035 [P] [US2] Add failing CLI tests for required expected project ID, wrong-project zero-write behavior, default/repeated datasets, dry-run no-write behavior, verified sync JSON, stale reporting, output-file handling, and infrastructure exit code `2` in `tests/evals/test_sync_evaluation_cli.py`

### Implementation for User Story 2

- [X] T036 [US2] Add the `sync-evaluation-datasets` parser/handler from `contracts/evaluation-cli.md` to `src/company_lens/evals/cli.py` using the foundational sync and score-config services
- [X] T037 [US2] Document deterministic IDs, active/archive semantics, dry-run, exact-version verification, and repository ownership in `evals/datasets/golden/README.md`
- [X] T038 [US2] Run US2 idempotency and mismatch validation in `tests/evals/test_langfuse_sync.py` and `tests/evals/test_sync_evaluation_cli.py`

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

- [X] T039 [P] [US3] Add failing tests for PR repository/head-SHA validation, canonical marker lookup/create/update, duplicate detection, sanitized body generation with created-run links and unavailable markers, API/permission failures, and reporting success/failure outcomes in `tests/evals/test_github_reporting.py`
- [X] T040 [P] [US3] Add a failing workflow contract test for `workflow_dispatch` inputs, Testing credentials/expected project ID, permissions, fixed dataset allowlist, captured exit code, signal forwarding, conditional recovery, paired repository/PR intent, sanitized preflight-failure reporting without provider calls, matching-target enforcement, reporting terminalization before unconditional journal/artifact upload, immutable execution JSON, and final status propagation in `tests/evals/test_evaluation_workflow.py`

### Implementation for User Story 3

- [X] T041 [US3] Implement typed GitHub PR lookup/comment reporting with the stable marker and privacy-safe errors in `src/company_lens/evals/github_reporting.py`
- [X] T042 [US3] Add the contracted `report-evaluation-pr` parser/handler that validates matching execution/journal artifacts, renders only allowlisted typed fields, and atomically terminalizes only journal reporting state/failure codes while proving execution JSON bytes and evaluation fields remain unchanged in `src/company_lens/evals/cli.py`
- [X] T043 [US3] Replace free-form dataset input with `all|core|follow_up`, pass the optional repository/PR pair to initialize reporting intent, verify the Testing Langfuse project ID, run the orchestrator with signal forwarding, recover missing final artifacts from the journal, invoke `report-evaluation-pr` with matching artifacts, upload the reporting-terminal artifact directory unconditionally, and propagate exit codes in `.github/workflows/eval-full.yml`
- [X] T044 [US3] Run the US3 focused suite in `tests/evals/test_github_reporting.py` and `tests/evals/test_evaluation_workflow.py`

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

- [X] T045 [US4] Replace starter-count assertions with failing foundation coverage, citation-mode/challenge-attempt semantics, category-minimum, citation-valid expected-answer, and framework-neutrality tests in `tests/test_golden_dataset.py`

### Implementation for User Story 4

- [X] T046 [US4] Annotate the existing seven core cases and four follow-up cases with reviewed effective citation modes/scenarios in `evals/datasets/golden/core.v1.yaml` and `evals/datasets/golden/follow_up.v1.yaml`
- [X] T047 [US4] Add seven reviewed core cases covering the second case in each non-follow-up category and the missing/unknown-evidence/semantic-mismatch citation challenge attempts, each expecting a valid final answer, within the 18-case total in `evals/datasets/golden/core.v1.yaml`
- [X] T048 [US4] Document category and citation-scenario authoring rules plus the 18-25 coverage invariant in `evals/datasets/golden/README.md`
- [X] T049 [US4] Run golden validation and deterministic regression tests in `tests/test_golden_dataset.py`, `tests/test_deterministic_evals.py`, and `tests/test_golden_agent_runner.py`

**Checkpoint**: The initial foundation dataset has balanced critical coverage and remains the sole
reviewed source of truth for synchronized Langfuse items.

---

## Phase 7: Polish and Cross-Cutting Validation

**Purpose**: Finish operational documentation, contract/security checks, graph freshness, and
end-to-end validation across all selected stories.

- [X] T050 [P] Add normal/replay/recovery evaluation, required environment and expected Langfuse project ID, dataset/run/score/journal inspection, exit-code triage, interruption recovery, and privacy guidance to `docs/operations.md`
- [X] T051 [P] Add forbidden-content scans across JSON, Markdown, score comments, CLI errors, and PR bodies in `tests/evals/test_evaluation_reporting.py` and `tests/test_observability_security.py`
- [X] T052 [P] Validate generated execution artifacts, every allowed journal phase/status/gate/reporting/target combination including reporting with failed preflight markers, representative rejected combinations including running with those same failed markers, strict nested manifests, and repository score contracts against `specs/003-langfuse-evaluation-foundation/contracts/evaluation-execution.schema.json`, `specs/003-langfuse-evaluation-foundation/contracts/evaluation-journal.schema.json`, and `specs/003-langfuse-evaluation-foundation/contracts/score-contract.schema.json` in `tests/evals/test_contract_schemas.py`
- [X] T053 Execute the non-provider setup, golden validation, wrong-project zero-write check, sync dry-run, exact-sync idempotency, read-only manifest replay, journal recovery, and focused failure scenarios from `specs/003-langfuse-evaluation-foundation/quickstart.md`, correcting command/document drift in that file
- [X] T054 Run `graphify update .` and review generated impact for the evaluation modules recorded in `graphify-out/graph.json`
- [X] T055 Run the full repository quality gate with `make check` and resolve all failures in the files changed by feature 003
- [X] T056 Run `.github/workflows/eval-full.yml` manually against a Testing PR/ref, verify expected project identity, exact reporting target/status, journal/final artifacts, Langfuse dataset-run links, recovery behavior, immutable evaluation output across reporting, and one canonical PR comment, and record any environment-only limitation in `specs/003-langfuse-evaluation-foundation/quickstart.md`

## Phase 8: Live Full-Suite Remediation

**Purpose**: Correct evaluator false negatives and parser resilience issues exposed by the first
18-case live execution without hiding genuine agent-quality or budget failures.

- [X] T057 Clarify every follow-up prompt and expected operation in `evals/datasets/golden/follow_up.v1.yaml`, require explicit inherited operations in `src/company_lens/evals/golden.py`, and add contract tests
- [X] T058 Make deterministic follow-up company rules accept reviewed name/ticker aliases while preserving status/source checks, extract the cohesive logic to `src/company_lens/evals/follow_up_checks.py`, and add ticker-only regression tests
- [X] T059 Classify schema-invalid OpenAI structured output as a recoverable provider response and verify the workflow retries it within policy
- [X] T060 Run targeted follow-up and core infrastructure smoke evaluations on commit `79e23219`, inspect the resulting Langfuse runs and canonical PR comment, confirm the evaluator/parser remediation, and isolate the remaining production-agent context/preparation failures before a full rerun

---

## Phase 9: Production Agent Follow-up and Preparation Remediation

**Purpose**: Fix the production-agent defects exposed by trustworthy deterministic evaluation:
require only the data each capability needs, preserve deterministic follow-up context, avoid duplicate
model extraction, and retain per-company provenance without weakening any evaluation threshold.

**Independent Test**: The four reviewed follow-up cases score `1.0` for operation accuracy and
citations, satisfy the existing operational budgets, and show no SEC/document/embedding work or
duplicate entity extraction for financial-only requests. The full 18-case workflow may run only
after this focused gate passes.

- [X] T061 [P] [US4] Add failing requirement-scoped readiness and pipeline-selection tests in `tests/test_on_demand_preparation.py`
- [X] T062 [P] [US4] Add failing inherit/replace/extend company-set, metric/operation retention, and mixed-provenance tests in `tests/agent_workflow/test_followup_company_sets.py` and `tests/agent_workflow/test_preparation_resolution.py`
- [X] T063 [P] [US4] Add failing capability-forwarding and no-duplicate-model-extraction tests in `tests/agent_workflow/test_prepared_followup_ticker.py`
- [X] T064 [US4] Extract typed `CompanyDataPreparationRequirements` and requirement-scoped readiness helpers from `src/company_lens/ingestion/on_demand.py` into `src/company_lens/ingestion/preparation_requirements.py`
- [X] T065 [US4] Refactor `src/company_lens/ingestion/on_demand.py` to execute financial-fact and document pipelines only when required and to apply requirement-scoped readiness
- [X] T066 [US4] Extend the `ResearchTools.prepare_companies` protocol, SQL adapter, and affected test fakes in `src/company_lens/agent/tools.py` and `tests/` to accept typed preparation requirements
- [X] T067 [US4] Derive preparation requirements from `AgentCapability` and finalize research context even when no external preparation is needed in `src/company_lens/agent/workflow_preparation.py`
- [X] T068 [US4] Replace post-preparation model entity extraction with deterministic local ticker enrichment in `src/company_lens/agent/workflow_preparation.py`
- [X] T069 [US4] Implement deterministic inherit/replace/extend follow-up rules while preserving requested metrics and operations in `src/company_lens/agent/workflow_followup_merge.py` and `src/company_lens/agent/workflow_followup_intent.py`
- [X] T070 [US4] Build per-company provenance from the pre-merge current query and final merged query in `src/company_lens/agent/workflow_frame.py` and its workflow call sites
- [X] T071 [US4] Add privacy-safe preparation-requirement details to workflow trajectory and telemetry, with regression coverage in the affected workflow tests
- [X] T072 [US4] Run the focused remediation tests and the full local quality gate from `specs/003-langfuse-evaluation-foundation/quickstart.md`
- [X] T073 [US4] Run `graphify update .` and inspect the generated impact for the modified ingestion and workflow modules
- [X] T074 [US4] Run the four-case follow-up live workflow, inspect Langfuse traces and the canonical PR comment, and require every deterministic metric and operational budget to pass
- [X] T075 [US4] Run the full 18-case live workflow only after T074 passes and record final evidence in `specs/003-langfuse-evaluation-foundation/quickstart.md`

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
- **Live Remediation (Phase 8)**: Depends on the first full live workflow execution after Phase 7.
- **Production Agent Remediation (Phase 9)**: Depends on the trustworthy evaluator/parser evidence
  from Phase 8 and the approved `follow-up-remediation-design.md`.

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
| FR-001-FR-005, FR-026, FR-028, FR-030, FR-033 | T003-T004, T007-T009, T015-T019, T035-T038, T040, T043, T050, T053, T056 |
| FR-006-FR-014, FR-018-FR-021, FR-027, FR-032, FR-034 | T005, T010, T022-T034, T040, T043, T050-T053, T056 |
| FR-015, FR-022-FR-024, FR-029 | T045-T049 |
| FR-016 | T011, T024, T051-T052 |
| FR-017 | T022-T030, T039-T044, T050-T052 |
| FR-025 | T022-T031 |
| FR-031 | T006, T010-T011, T018, T024, T052 |
| FR-035 | T005, T030, T039-T044, T051-T053, T056 |
| FR-036-FR-037 | T057-T060 |
| FR-038-FR-040 | T061-T075 |
| FR-041 | T023, T028 |
| SC-001-SC-017 | T021, T034, T038, T044, T049, T051-T056, T060 |
| SC-018-SC-019 | T061-T075 |
| SC-020 | T023, T028 |

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
- Phase 9 red tests T061-T063 can be authored in parallel before the sequential production changes.

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
6. **Production remediation**: Capability-aware preparation, deterministic follow-up merging,
   targeted live evidence, then the full 18-case rerun.

### Commit and Validation Discipline

- Keep tests red before the implementation task they specify.
- Commit after each task or cohesive task group; do not mix unrelated refactors.
- Run focused tests at every story checkpoint and `make check` before every commit.
- After code modifications, run `graphify update .` before final delivery.
- Do not add LLM-as-judge, annotation queues, calibration, or production monitoring in feature 003.
