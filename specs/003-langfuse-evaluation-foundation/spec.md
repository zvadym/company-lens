# Feature Specification: Langfuse Evaluation Foundation

**Feature Branch**: `003-langfuse-evaluation-foundation`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Create a Spec Kit feature for a repo-driven Langfuse evaluation foundation. Repository golden datasets remain the source of truth, selected cases sync to Langfuse, manual live evaluations publish deterministic and citation-validation scores, and PR reviewers can inspect a summarized manual result without making it a required PR gate. LLM-as-judge, annotation queues, and judge calibration are reserved for a follow-up feature."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Manual Evaluation Visible In Langfuse (Priority: P1)

A maintainer can manually run a live evaluation for selected golden datasets and inspect the resulting case outcomes, scores, and gate result in Langfuse and local artifacts.

**Why this priority**: This is the core value of the feature. The team already has local golden datasets and deterministic evaluation logic, but the results are not yet visible as Langfuse dataset or experiment runs.

**Independent Test**: Run the manual evaluation workflow against one selected dataset and verify that every selected case produces a recorded result, score summary, gate outcome, local report artifact, and Langfuse-visible run.

**Acceptance Scenarios**:

1. **Given** a selected valid golden dataset and available evaluation credentials, **When** a maintainer runs the manual evaluation workflow, **Then** the selected cases are evaluated and a Langfuse-visible run is created with item-level and aggregate scores.
2. **Given** one or more selected cases fail expected behavior, **When** the evaluation completes, **Then** the run is marked failed, failed case IDs and short reasons are reported, and successful case results remain inspectable.
3. **Given** the evaluation gate fails, **When** the manual workflow completes, **Then** the manual workflow result is visibly failed while no required PR-blocking check is created by this feature.

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

1. **Given** a valid PR number is supplied, **When** the evaluation completes, **Then** the pull request receives a summary comment with dataset names, case count, branch/ref, commit SHA, gate result, score summary, failed case reasons, artifact links, and Langfuse run links.
2. **Given** the workflow is rerun for the same PR, **When** a previous evaluation comment exists, **Then** the existing comment is updated or clearly superseded instead of creating confusing duplicate summaries.
3. **Given** PR reporting fails after evaluation succeeds, **When** the workflow completes, **Then** the evaluation artifacts and Langfuse run remain valid and the reporting failure is visible in the workflow result.

---

### User Story 4 - Expand Critical Golden Coverage (Priority: P4)

An agent developer can add reviewed critical cases to the repository dataset so the foundation evaluates more than the current starter set.

**Why this priority**: The existing 11 cases are a useful start but too small to build confidence in a solid agent. The foundation should cover the highest-risk behaviors before adding subjective judge-based evaluation.

**Independent Test**: Review the repository datasets and verify that the first foundation release covers at least 18 and no more than 25 critical cases across core routing, citations, ambiguity, abstention, adversarial instructions, hybrid answers, and follow-up safety.

**Acceptance Scenarios**:

1. **Given** the foundation dataset expansion is complete, **When** the datasets are validated, **Then** they include critical cases for structured facts, document retrieval, hybrid answers, ambiguous companies, future or missing facts, prompt-injection style instructions, citation validation, and follow-up context reuse.
2. **Given** a developer changes or adds a golden case, **When** the dataset is reviewed, **Then** the expected behavior remains expressed in framework-neutral repository data rather than only in Langfuse.

### Edge Cases

- Langfuse credentials are missing, invalid, or point to the wrong project.
- A repository dataset contains duplicate case IDs, invalid expected behavior, or unsupported fields.
- Langfuse sync succeeds for some work before a later failure; the sync report must make partial completion clear and the evaluation must not claim a trustworthy completed sync.
- A live agent run times out, is interrupted, or returns no final answer for a case.
- Citation validation cannot run because the final answer or evidence registry is missing.
- A PR number is invalid, unavailable to the workflow, or lacks permission for comments.
- A dataset has stale remote cases that no longer exist in the repository source of truth.
- A gate fails because of behavior regressions, missing results, citation failures, or operational budget violations.
- Reports and comments must summarize results without exposing raw prompts, provider payloads, hidden reasoning, credentials, stack traces, raw retrieved passages, or citation-invalid drafts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat repository golden dataset files as the source of truth for foundation evaluation cases.
- **FR-002**: The system MUST validate selected golden datasets before synchronization or live evaluation begins.
- **FR-003**: The system MUST synchronize selected repository datasets and cases into Langfuse with stable case identity and source metadata.
- **FR-004**: Dataset synchronization MUST be idempotent for unchanged cases.
- **FR-005**: Dataset synchronization MUST identify stale remote cases that are no longer present in the selected repository dataset.
- **FR-006**: The manual evaluation workflow MUST allow maintainers to select dataset scope, maximum case count, execution configuration, and optional PR reporting target.
- **FR-007**: The manual evaluation workflow MUST run the live research agent against selected cases using isolated sessions per case.
- **FR-008**: The system MUST record observed case behavior, deterministic checks, citation validation results, and operational metrics when available.
- **FR-009**: The system MUST publish item-level scores for overall case pass, company accuracy, metric accuracy, operation accuracy, route accuracy, required tool recall, prohibited tool pass, follow-up safety, citation validity, and operational budget pass when applicable.
- **FR-010**: The system MUST publish run-level aggregate scores for dataset pass rate, category pass rate, citation validity pass rate, missing result rate, operational metrics presence rate, and gate pass/fail.
- **FR-011**: Versioned regression gates MUST remain repository-authored and reviewed with the evaluation datasets.
- **FR-012**: A failed gate MUST make the manual workflow visibly fail without creating a required PR-blocking gate in this feature.
- **FR-013**: The system MUST create local machine-readable and human-readable evaluation artifacts for each manual run.
- **FR-014**: When a PR number is supplied, the system MUST create or update a concise PR evaluation summary that links to local artifacts and Langfuse results.
- **FR-015**: The first foundation release MUST expand the selected golden coverage from the current 11 cases to at least 18 and no more than 25 critical cases.
- **FR-016**: The foundation MUST NOT emit LLM-as-judge scores, create annotation queues, or perform judge calibration; those belong to a follow-up evaluation quality-loop feature.
- **FR-017**: Reports, scores, comments, and public artifacts MUST preserve privacy-safe observability boundaries and avoid exposing raw prompts, provider payloads, hidden reasoning, credentials, stack traces, raw retrieved passages, or citation-invalid drafts.
- **FR-018**: The system MUST distinguish behavior failures from evaluation infrastructure failures in summaries and artifacts.
- **FR-019**: Partial evaluation runs MUST preserve available artifacts and Langfuse records while clearly failing the gate when selected cases are missing or incomplete.

### Key Entities

- **Golden Dataset**: A repository-authored collection of evaluation cases with a stable name, version, description, and categories.
- **Golden Case**: A stable case ID, conversation, expected behavior, category, and optional notes used to evaluate one agent behavior.
- **Synchronized Dataset Item**: The Langfuse-visible representation of one repository golden case, including metadata that links it back to dataset name, version, source path, category, and case ID.
- **Evaluation Run**: One manual execution of selected golden cases against a branch/ref and configuration, with observed outputs, score summaries, artifacts, and Langfuse links.
- **Evaluation Score**: A deterministic or citation-validation outcome attached to a case or run.
- **Regression Gate**: A repository-authored set of pass/fail thresholds for evaluation metrics and operational budgets.
- **PR Evaluation Summary**: A pull-request comment summarizing the manual evaluation status, selected datasets, scores, failed cases, artifact links, and Langfuse links.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer can synchronize selected repository datasets and verify that 100% of selected case IDs appear once in Langfuse after a successful sync.
- **SC-002**: Re-running synchronization for unchanged selected datasets does not create duplicate Langfuse items for any stable case ID.
- **SC-003**: A manual evaluation run creates Langfuse-visible results and local artifacts for 100% of selected cases, including failed or missing-case records.
- **SC-004**: Evaluation summaries include pass/fail status, selected dataset names, case counts, aggregate scores, failed case IDs, short failure reasons, and Langfuse links for every completed manual run.
- **SC-005**: When a valid PR number is supplied, the manual workflow creates or updates a PR summary comment for at least 95% of successful reporting attempts; failures remain visible through workflow output and artifacts.
- **SC-006**: Gate failures cause the manual workflow to finish with a visible failed result while leaving the PR free of a required blocking evaluation check in this feature.
- **SC-007**: The initial foundation coverage contains at least 18 and no more than 25 reviewed golden cases spanning the critical categories named in this specification.
- **SC-008**: No foundation evaluation run emits LLM-as-judge scores, annotation queue items, or judge-calibration results.
- **SC-009**: Public reports and PR comments contain zero raw prompts, provider payloads, hidden reasoning, credentials, stack traces, raw retrieved passages, or citation-invalid drafts.

## Assumptions

- The repository remains the reviewed source of truth for foundation datasets and gates.
- Langfuse is available as the evaluation visibility system for this feature.
- Manual evaluation runs may use provider credentials and are expected to be more expensive and slower than ordinary local checks.
- PR reporting is useful for review visibility but is not a required approval gate in this feature.
- Existing deterministic evaluation models, citation validation behavior, and live agent runner concepts remain the starting point for this foundation.
- The follow-up feature will cover LLM-as-judge calibration, annotation queues, error taxonomy, and production-quality monitoring.
