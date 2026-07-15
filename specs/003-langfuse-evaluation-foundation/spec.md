# Feature Specification: Langfuse Evaluation Foundation

**Feature Branch**: `003-langfuse-evaluation-foundation`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Create a Spec Kit feature for a repo-driven Langfuse evaluation foundation. Repository golden datasets remain the source of truth, selected cases sync to Langfuse, manual live evaluations publish deterministic and citation-validation scores, and PR reviewers can inspect a summarized manual result without making it a required PR gate. LLM-as-judge, annotation queues, and judge calibration are reserved for a follow-up feature."

## Clarifications

### Session 2026-07-09

- Q: How should multiple repository datasets map to Langfuse experiment runs? → A: Preserve a one-to-one mapping between repository and Langfuse datasets, create one Langfuse experiment run per selected dataset, and group all runs from one manual invocation under a shared evaluation execution ID and summary.
- Q: How should evaluation infrastructure failures affect the evaluation gate? → A: Fail the workflow and mark the execution partial or errored, but report the gate as not evaluated when infrastructure prevents a complete trustworthy evaluation; agent timeouts or missing answers that are successfully captured as observed behavior remain behavior failures evaluated by the gate.
- Q: How should citation validation applicability be defined for golden cases? → A: Each golden case has an effective citation mode of required or not applicable, omitted values default to required, and cases marked not applicable are excluded from citation pass-rate denominators.
- Q: How strictly should an evaluation execution guarantee reproducibility? → A: Before provider calls, validate and synchronize selected datasets, verify their remote counts and content hashes, pin the exact remote dataset snapshots, and persist an immutable run manifest; snapshot mismatch is an infrastructure error with a not-evaluated gate.
- Q: What minimum structure should the expanded golden coverage satisfy? → A: Include at least two cases in every existing golden-case category and cover valid, missing, unknown-evidence, and semantic-mismatch citation scenarios, allowing citation scenarios to overlap category cases within the 18-to-25-case total.

### Session 2026-07-10

- Q: What does reproducible execution from a recorded manifest mean in feature 003? → A: The CLI accepts an existing local execution manifest, validates the referenced repository content and immutable configuration, reopens the exact Langfuse dataset snapshots without synchronizing or mutating them, creates a new execution ID linked to the source execution, and fails before provider calls when any pinned input is unavailable or mismatched.
- Q: How does preflight prove that credentials target the intended Langfuse project? → A: Evaluation and synchronization require an expected Langfuse project ID, resolve the project associated with the configured project-scoped API key through the public project endpoint, and fail before remote writes or provider calls when identity is unavailable or mismatched.
- Q: How are artifacts preserved when an evaluation process is interrupted? → A: The orchestrator creates an atomic recovery journal before remote preflight and replaces it after every terminal preflight, case, dataset-run, and reporting transition; graceful termination finalizes partial JSON and Markdown from that journal, while uncatchable termination still leaves the latest journal checkpoint for deterministic recovery.
- Q: Do missing, unknown-evidence, and semantic-mismatch citation scenarios expect invalid final answers? → A: No. They are challenge-attempt metadata describing the failure mode the case is designed to resist; every citation-required golden case still expects a citation-valid final answer.
- Q: How is optional PR reporting represented without changing the evaluation verdict? → A: The recovery journal has a separate `not_requested|pending|succeeded|failed` reporting status. The reporting command may advance only that status and reporting failure codes; evaluation status, gate status, manifest, runs, scores, and final execution JSON remain unchanged.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Manual Evaluation Visible In Langfuse (Priority: P1)

A maintainer can manually run a live evaluation for selected golden datasets and inspect the resulting case outcomes, scores, and gate result in Langfuse and local artifacts.

**Why this priority**: This is the core value of the feature. The team already has local golden datasets and deterministic evaluation logic, but the results are not yet visible as Langfuse dataset or experiment runs.

**Independent Test**: Run the manual evaluation workflow against one selected dataset and verify that every selected case produces a recorded result, score summary, gate outcome, local report artifact, and Langfuse-visible run.

**Acceptance Scenarios**:

1. **Given** a selected valid golden dataset and available evaluation credentials, **When** a maintainer runs the manual evaluation workflow, **Then** the selected cases are evaluated and a Langfuse-visible run is created with item-level and aggregate scores.
2. **Given** one or more selected cases fail expected behavior, **When** the evaluation completes, **Then** the run remains completed, the evaluation gate is marked failed, failed case IDs and short reasons are reported, and successful case results remain inspectable.
3. **Given** the evaluation gate fails, **When** the manual workflow completes, **Then** the manual workflow result is visibly failed while no required PR-blocking check is created by this feature.
4. **Given** multiple repository datasets are selected, **When** the manual evaluation completes, **Then** each dataset has its own Langfuse experiment run and all resulting runs share one evaluation execution ID and aggregate summary.
5. **Given** an infrastructure failure prevents a complete trustworthy evaluation, **When** the workflow terminates, **Then** the workflow fails, available records and artifacts are preserved, the execution is marked partial or errored, and the evaluation gate is marked not evaluated rather than failed.
6. **Given** an agent timeout or missing final answer is successfully captured as the observed outcome for a selected case, **When** deterministic evaluation runs, **Then** the case is treated as a behavior failure and remains part of the evaluation gate.
7. **Given** selected repository datasets and valid Langfuse credentials, **When** a manual evaluation starts, **Then** dataset validation, synchronization, remote count and content-hash verification, and exact snapshot selection complete before any provider-backed agent case runs.
8. **Given** the synchronized remote dataset does not match the selected repository source, **When** preflight verification completes, **Then** no provider-backed case runs, the workflow fails as an infrastructure error, and the evaluation gate is marked not evaluated.
9. **Given** a recorded manifest and unchanged repository and external services, **When** a maintainer re-runs the evaluation from that manifest, **Then** a new linked execution uses the same repository content, exact remote snapshots, gate, model configuration, prompt/parser/index versions, score contract, and execution policy without synchronizing or mutating remote datasets.
10. **Given** configured credentials are valid but belong to a different Langfuse project than the expected project ID, **When** evaluation preflight runs, **Then** no remote dataset write or provider-backed case call occurs and the execution is errored with a not-evaluated gate.
11. **Given** the evaluation process is interrupted after work begins, **When** artifacts are collected or execution is recovered, **Then** the latest atomic journal contains every terminal transition completed before interruption and can produce a privacy-safe partial execution artifact.

---

### User Story 2 - Sync Repo Golden Cases To Langfuse (Priority: P2)

A maintainer can synchronize selected repository-authored golden datasets into Langfuse so the Langfuse dataset view matches reviewed repository cases.

**Why this priority**: Repository YAML must remain the reviewed source of truth. Automated synchronization prevents silent drift between the repo and Langfuse.

**Independent Test**: Run dataset sync twice against the same valid dataset and verify that the same case IDs exist once in Langfuse with metadata linking them back to the repository dataset, version, category, and case ID.

**Acceptance Scenarios**:

1. **Given** a valid repository dataset, **When** dataset sync runs, **Then** Langfuse contains one item per selected case with stable identity and source metadata.
2. **Given** dataset sync already ran for unchanged cases, **When** it runs again, **Then** existing items are refreshed rather than duplicated.
3. **Given** a case was removed or renamed in the repository dataset, **When** sync runs, **Then** the sync report identifies stale remote cases and future evaluation runs select only repository-present cases.

---

### User Story 3 - Review Manual Evaluation From A PR (Priority: P3)

A reviewer can see a concise manual evaluation summary on a pull request when the maintainer supplies a PR number for the manual run.

**Why this priority**: The evaluation should be easy to review where code review is happening, without requiring every reviewer to search through workflow logs.

**Independent Test**: Run the manual evaluation workflow with a PR number and verify that a stable PR comment is created or updated with pass/fail state, score summary, failed cases, artifacts, and Langfuse links.

**Acceptance Scenarios**:

1. **Given** a valid PR number is supplied, **When** the evaluation completes, **Then** the pull request receives a summary comment with dataset names, case count, branch/ref, commit SHA, gate result, score summary, failed case reasons, artifact links, a link for every created Langfuse run, and an explicit unavailable marker for any dataset that produced no run.
2. **Given** the workflow is rerun for the same PR, **When** a previous evaluation comment exists, **Then** the existing comment is updated or clearly superseded instead of creating confusing duplicate summaries.
3. **Given** PR reporting fails after evaluation succeeds, **When** the workflow completes, **Then** the evaluation artifacts and Langfuse run remain valid, the journal records `reporting_status=failed`, the evaluation status and gate remain unchanged, and the reporting failure is visible in the workflow result.
4. **Given** project or dataset preflight fails with a PR target before provider-backed cases begin, **When** reporting runs from the frozen failure manifest, **Then** the PR receives a sanitized infrastructure/not-evaluated summary without requiring verified snapshots, aggregate quality scores, or raw remote errors.

---

### User Story 4 - Expand Critical Golden Coverage (Priority: P4)

An agent developer can add reviewed critical cases to the repository dataset so the foundation evaluates more than the current starter set.

**Why this priority**: The existing 11 cases are a useful start but too small to build confidence in a solid agent. The foundation should cover the highest-risk behaviors before adding subjective judge-based evaluation.

**Independent Test**: Review the repository datasets and verify that the first foundation release contains at least 18 and no more than 25 critical cases, includes at least two cases in every existing golden-case category, and covers valid, missing-attempt, unknown-evidence-attempt, and semantic-mismatch-attempt citation scenarios.

**Acceptance Scenarios**:

1. **Given** the foundation dataset expansion is complete, **When** the datasets are validated, **Then** they include critical cases for structured facts, document retrieval, hybrid answers, ambiguous companies, future or missing facts, prompt-injection style instructions, citation validation, and follow-up context reuse.
2. **Given** a developer changes or adds a golden case, **When** the dataset is reviewed, **Then** the expected behavior remains expressed in framework-neutral repository data rather than only in Langfuse.
3. **Given** a golden case is authored or updated, **When** the dataset is validated, **Then** its citation mode is explicitly valid or defaults to required, and not-applicable mode is used only when the expected response contains no material source-derived claim requiring citation validation.
4. **Given** the foundation coverage is validated, **When** cases are grouped by category, **Then** every existing golden-case category contains at least two reviewed cases.
5. **Given** citation coverage is validated, **When** citation-required cases are inspected, **Then** the suite includes a valid-citation baseline plus missing-citation, unknown-evidence, and semantic-mismatch challenge attempts involving company, period, number, or calculation lineage, and every case expects a citation-valid final answer.

### Edge Cases

- Langfuse credentials are missing or invalid, the expected project ID is missing, or the key-associated project identity does not match it.
- A repository dataset contains duplicate case IDs, invalid expected behavior, or unsupported fields.
- Langfuse sync succeeds for some work before a later failure; the sync report must make partial completion clear and the evaluation must not claim a trustworthy completed sync.
- A synchronized Langfuse dataset has an unexpected item count or content hash and cannot be verified as the exact repository-authored snapshot selected for the run.
- A live agent run times out or returns no final answer and the runner successfully captures that terminal behavior for the case.
- The runner, provider, synchronization, or evaluator fails before it can produce a complete trustworthy result.
- A citation-required case produces a captured missing answer, missing evidence, unknown evidence ID, wrong company or period citation, unsupported number, or incomplete calculation lineage.
- Citation validation infrastructure fails before it can produce a trustworthy result for a citation-required case.
- A PR number is invalid, unavailable to the workflow, or lacks permission for comments.
- A dataset has stale remote cases that no longer exist in the repository source of truth.
- A gate fails because of behavior regressions, missing results, citation failures, or operational budget violations.
- Reports and comments must summarize results without exposing raw prompts, provider payloads, hidden reasoning, credentials, stack traces, raw retrieved passages, or citation-invalid drafts.
- A replay manifest references repository content, a remote snapshot, score contract, gate, prompt/parser/index version, model configuration, or execution policy that is missing or no longer matches.
- The process receives graceful termination after some terminal records were journaled, or is killed without an opportunity to finalize user-facing artifacts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat repository golden dataset files as the source of truth for foundation evaluation cases.
- **FR-002**: The system MUST validate selected golden datasets before synchronization and complete synchronization verification before any provider-backed live evaluation begins.
- **FR-003**: The system MUST synchronize each selected repository dataset to one corresponding Langfuse dataset with stable case identity and source metadata.
- **FR-004**: Dataset synchronization MUST be idempotent for unchanged cases.
- **FR-005**: Dataset synchronization MUST identify stale remote cases that are no longer present in the selected repository dataset.
- **FR-006**: The manual evaluation workflow MUST allow maintainers to select one or more datasets, a per-dataset maximum case count, execution configuration, and an optional PR reporting target.
- **FR-007**: The manual evaluation workflow MUST run the live research agent against selected cases using isolated sessions per case.
- **FR-008**: The system MUST record observed case behavior, deterministic checks, citation validation results, operational metrics, and explicit missing markers for any expected result that could not be produced.
- **FR-009**: The system MUST publish the canonical BOOLEAN item scores `case_pass`, `company_pass`, `metric_pass`, `operation_pass`, `route_pass`, `required_tools_pass`, `prohibited_tools_pass`, `follow_up_safety_pass`, `citation_valid` for citation-required cases, and `operational_budget_pass` according to the versioned score contract's applicability rules.
- **FR-010**: The system MUST publish the canonical run-level scores `case_pass_rate`, `company_accuracy`, `metric_accuracy`, `operation_accuracy`, `route_accuracy`, `required_tool_recall`, `prohibited_tool_pass_rate`, `follow_up_safety_accuracy`, `citation_validity_pass_rate` over citation-required cases only, `operational_metrics_presence_rate`, `operational_budget_pass_rate`, `missing_result_rate`, the eight `category_*` scores defined by the score contract, and `gate_status`.
- **FR-011**: Versioned evaluation gates MUST remain repository-authored and reviewed with the evaluation datasets.
- **FR-012**: A failed gate MUST make the manual workflow visibly fail without creating a required PR-blocking gate in this feature.
- **FR-013**: The system MUST create local machine-readable and human-readable evaluation artifacts for each manual run.
- **FR-014**: When a PR number is supplied, the system MUST create or update a concise PR evaluation summary that links to local artifacts and every created Langfuse run and explicitly marks Langfuse run output unavailable for datasets that fail before a run is created.
- **FR-015**: The first foundation release MUST expand the selected golden coverage from the current 11 cases to at least 18 and no more than 25 critical cases, with at least two reviewed cases in each of these categories: document retrieval, structured financial, hybrid, cross-document comparison, ambiguous entity, missing data or abstention, adversarial or prompt injection, and follow-up.
- **FR-016**: The foundation MUST NOT emit LLM-as-judge scores, create annotation queues, or perform judge calibration; those belong to a follow-up evaluation quality-loop feature.
- **FR-017**: Reports, scores, comments, and public artifacts MUST preserve privacy-safe observability boundaries and avoid exposing raw prompts, provider payloads, hidden reasoning, credentials, stack traces, raw retrieved passages, or citation-invalid drafts.
- **FR-018**: The system MUST distinguish behavior failures from evaluation infrastructure failures in Langfuse records, summaries, artifacts, and workflow outcomes.
- **FR-019**: Evaluation infrastructure failures that prevent a complete trustworthy evaluation MUST fail the workflow, preserve available artifacts and Langfuse records, mark the execution partial or errored, and mark the evaluation gate not evaluated rather than failed.
- **FR-020**: A manual invocation that selects multiple repository datasets MUST create one Langfuse experiment run per selected dataset and group those runs under one shared evaluation execution ID, artifact set, and optional PR summary.
- **FR-021**: An agent timeout, missing final answer, or similar terminal outcome that the runner successfully captures for a selected case MUST be recorded as an observed behavior failure and included in evaluation gate calculations.
- **FR-022**: Every golden case MUST resolve to a citation mode of required or not applicable, with omitted values normalized to required for backward compatibility.
- **FR-023**: Citation-required cases MUST fail citation validation when a captured result has no final answer or required evidence, or has unknown evidence IDs, wrong-company or wrong-period citations, unsupported numbers, or incomplete calculation lineage.
- **FR-024**: Cases with citation mode not applicable MUST be excluded from citation validity pass-rate denominators and MUST NOT emit a misleading boolean or numeric citation-validity score.
- **FR-025**: A failure of citation-validation infrastructure to produce a trustworthy result MUST be classified as an infrastructure failure and handled according to the not-evaluated gate policy.
- **FR-026**: Before any provider-backed case runs, the system MUST synchronize each selected repository dataset, verify the count and content hashes of the repository-present remote item set, exclude identified stale remote items, and select the exact verified remote dataset snapshot and item set for the experiment run.
- **FR-027**: Every evaluation execution MUST persist an immutable run manifest in local artifacts containing the commit SHA; dataset names, versions, source paths, content hashes, selected case IDs, and verified remote snapshot identifiers or explicit unavailable markers; expected/resolved Langfuse project identity; gate name, version, and content hash; score contract/config bindings or explicit unavailable markers; model and execution configuration; prompt, parser, and index versions; execution policy; and environment. Once remote preflight succeeds, the same manifest fingerprint MUST be stored in Langfuse execution metadata before provider-backed case calls.
- **FR-028**: A repository-present remote item-set count or content-hash mismatch that cannot be resolved during preflight MUST prevent provider-backed case execution, fail the workflow as an infrastructure error, and leave the evaluation gate not evaluated.
- **FR-029**: The expanded foundation dataset MUST cover a valid-citation baseline plus missing-citation, unknown-evidence, and semantic-mismatch challenge attempts involving company, period, number, or calculation lineage; these cases MAY also satisfy category coverage requirements, and every citation-required case MUST still expect a citation-valid final answer.
- **FR-030**: Synchronized item identity MUST be deterministic and project-unique from repository dataset name and stable case ID; dataset version and content hash MUST remain version metadata rather than changing item identity.
- **FR-031**: The foundation MUST maintain a repository-authored, versioned score contract defining each emitted score's canonical name, item or run scope, value type, applicability and denominator rules, and privacy-safe reason semantics, plus one contract-level evaluator version that applies to every definition in that contract version.
- **FR-032**: The system MUST support replay from a recorded local execution manifest by validating all immutable inputs, selecting the exact recorded Langfuse snapshots without synchronization or remote mutation, creating a new execution ID linked to the source execution, and making any unavailable or mismatched input an infrastructure failure before provider-backed case calls.
- **FR-033**: Synchronization and evaluation MUST require an expected Langfuse project ID and verify that the configured project-scoped credentials resolve to that exact project before any remote write or provider-backed case call; missing, unavailable, or mismatched identity MUST fail closed as infrastructure with a not-evaluated gate.
- **FR-034**: The orchestrator MUST atomically persist a privacy-safe recovery journal before remote preflight and after every terminal preflight, case, dataset-run, and reporting transition; graceful interruption MUST materialize partial JSON and Markdown artifacts, and uncatchable interruption MUST leave the latest valid journal checkpoint from which partial artifacts can be recovered.
- **FR-035**: Optional PR reporting MUST maintain an exact repository/PR target and a separate journal status of not requested, pending, succeeded, or failed; the reporting command MUST reject a target mismatch, MAY atomically advance only reporting status and sanitized reporting failure codes, and MUST NOT change evaluation status, gate status, manifest, runs, scores, or the final execution JSON.
- **FR-036**: Follow-up golden cases that inherit an operation MUST define that operation explicitly, and deterministic company checks MUST treat a reviewed company name and ticker as equivalent identities without weakening status or source checks.
- **FR-037**: Structured model output that fails response-schema validation MUST be classified as a recoverable provider-response failure and retried within the existing per-node policy; exhausted retries MUST remain a sanitized terminal outcome.
- **FR-038**: On-demand company preparation MUST derive typed financial-fact and document requirements from the analyzed agent capabilities; a financial-only route MUST NOT ingest SEC filings, process documents, or create embeddings.
- **FR-039**: Follow-up resolution MUST deterministically inherit, replace, or extend company sets from the current resolved companies and explicit add/include intent, preserve compatible metrics and operations, and record provenance separately for each final company target.
- **FR-040**: Completing or skipping on-demand preparation MUST enrich prepared tickers through deterministic local resolution and MUST NOT repeat model-based company extraction solely because preparation ran.

### Key Entities

- **Golden Dataset**: A repository-authored collection of evaluation cases with a stable name, version, description, and categories.
- **Golden Case**: A stable case ID, conversation, expected behavior, category, citation mode that defaults to required, and optional notes used to evaluate one agent behavior.
- **Synchronized Dataset Item**: The Langfuse-visible representation of one repository golden case, including metadata that links it back to dataset name, version, source path, category, and case ID.
- **Evaluation Run**: One dataset-specific execution of selected golden cases against a branch/ref and configuration, with observed outputs, score summaries, artifacts, Langfuse links, and a terminal status of completed, partial, or errored.
- **Evaluation Execution**: One manual workflow invocation that groups one or more dataset-specific evaluation runs under a shared execution ID, aggregate summary, and terminal status of completed, partial, or errored.
- **Evaluation Run Manifest**: An immutable, privacy-safe record of the exact code, datasets, remote snapshots, gate, models, prompt and parser versions, index version, execution policy, configuration, and environment used by one evaluation execution.
- **Evaluation Recovery Journal**: An atomically replaced, privacy-safe checkpoint of execution state and terminal transitions used to recover or materialize partial artifacts after interruption; it is not a substitute for the immutable run manifest.
- **Evaluation Score**: A deterministic or citation-validation outcome attached to a case or run and governed by the repository-authored versioned score contract.
- **Evaluation Gate**: A repository-authored set of thresholds for evaluation metrics and operational budgets with a terminal status of passed, failed, or not evaluated.
- **PR Evaluation Summary**: A pull-request comment summarizing the manual evaluation status, selected datasets, scores, failed cases, artifact links, and Langfuse links.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer can synchronize selected repository datasets and verify that 100% of selected case IDs appear once in Langfuse after a successful sync.
- **SC-002**: Re-running synchronization for unchanged selected datasets does not create duplicate Langfuse items for any stable case ID.
- **SC-003**: Every completed manual evaluation execution creates one Langfuse experiment run per selected repository dataset and local artifacts containing a terminal record for 100% of selected cases, including behavior failures and captured missing-case outcomes, with every run linked by the shared evaluation execution ID.
- **SC-004**: Evaluation summaries include pass/fail status, selected dataset names, case counts, aggregate scores, failed case IDs, short failure reasons, and Langfuse links for every completed manual run.
- **SC-005**: For every evaluation execution supplied with a valid PR number and sufficient workflow permissions, reporting creates or updates exactly one canonical PR summary comment; any reporting failure remains visible through workflow output and artifacts.
- **SC-006**: Gate failures cause the manual workflow to finish with a visible failed result while leaving the PR free of a required blocking evaluation check in this feature.
- **SC-007**: The initial foundation coverage contains at least 18 and no more than 25 reviewed golden cases, at least two cases in every existing golden-case category, and the valid baseline plus all three required citation challenge-attempt scenarios.
- **SC-008**: No foundation evaluation run emits LLM-as-judge scores, annotation queue items, or judge-calibration results.
- **SC-009**: Public reports and PR comments contain zero raw prompts, provider payloads, hidden reasoning, credentials, stack traces, raw retrieved passages, or citation-invalid drafts.
- **SC-010**: Every workflow failure is classified as either an evaluated behavior or gate failure, or an infrastructure failure with a not-evaluated gate; no infrastructure failure is reported as a quality regression.
- **SC-011**: Citation validity pass rates use exactly the citation-required cases as their denominator, while every not-applicable case is visibly identified and excluded without receiving a citation-validity score.
- **SC-012**: Re-running an evaluation from a recorded manifest against unchanged external services selects the same repository content, remote dataset snapshots, gate, model configuration, prompt and parser versions, index version, and execution policy.
- **SC-013**: Zero provider-backed case calls begin when selected repository datasets cannot be verified against their synchronized Langfuse snapshots.
- **SC-014**: Every score emitted by a foundation evaluation resolves to exactly one definition in the selected repository score-contract version, and no run mixes incompatible score definitions under the same canonical name.
- **SC-015**: In automated tests, a valid Langfuse key associated with a project ID different from the configured expected project ID causes zero remote writes and zero provider-backed case calls.
- **SC-016**: After each injected interruption boundary following a completed terminal transition, the recovery journal validates against its contract, contains all and only completed terminal records, exposes no forbidden content, and can materialize a partial execution with a not-evaluated gate.
- **SC-017**: Every workflow run with a PR target and valid matching execution/journal artifacts ends with journal reporting status succeeded or failed; an injected reporting failure leaves the previously materialized execution JSON byte-for-byte unchanged while the workflow exits `2` and the journal records only the sanitized reporting failure.
- **SC-018**: The targeted four-case follow-up evaluation reaches `1.0` for company accuracy, metric accuracy, operation accuracy, follow-up safety accuracy, and citation validity pass rate without increasing evaluation-gate thresholds.
- **SC-019**: Financial-only follow-up traces contain zero SEC document-processing and embedding operations, perform no duplicate post-preparation model company extraction, and pass the existing operational budgets.

## Assumptions

- The repository remains the reviewed source of truth for foundation datasets and gates.
- Langfuse is available as the evaluation visibility system for this feature.
- Manual evaluation runs may use provider credentials and are expected to be more expensive and slower than ordinary local checks.
- PR reporting is useful for review visibility but is not a required approval gate in this feature.
- Existing deterministic evaluation models, citation validation behavior, and live agent runner concepts remain the starting point for this foundation.
- The follow-up feature will cover LLM-as-judge calibration, annotation queues, error taxonomy, and production-quality monitoring.
