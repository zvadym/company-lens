# Feature Specification: Current Product Baseline

**Feature Branch**: `main`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Install GitHub Spec Kit and create a brief backlog for what already exists in CompanyLens."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Answer grounded company research questions (Priority: P1)

As an analyst, I can ask qualitative, numerical, or hybrid questions about public companies and receive an answer that uses the appropriate evidence path.

**Why this priority**: This is the core product value and the reason the rest of the system exists.

**Independent Test**: Ask one narrative filing question, one financial metric question, and one hybrid company-plus-macro question; each answer must use the correct evidence types and avoid unsupported claims.

**Acceptance Scenarios**:

1. **Given** a narrative risk question for a known public company, **When** the research run completes, **Then** the answer cites retrieved filing evidence.
2. **Given** a revenue growth question for a known public company, **When** the research run completes, **Then** the answer uses structured SEC facts and deterministic calculations.
3. **Given** a company growth versus macro question, **When** the research run completes, **Then** the answer combines financial facts, FRED observations, calculations, and a chart artifact when chart intent exists.

---

### User Story 2 - Inspect research run progress and results (Priority: P2)

As a user of the web interface or API, I can start a research run, inspect progress, view answer text, sources, trace events, and chart artifacts without seeing private prompts or raw provider internals.

**Why this priority**: The product needs transparency and debuggability without leaking sensitive internals.

**Independent Test**: Start a run through the API or UI and verify lifecycle metadata, SSE events, final result, sources, chart artifacts, and public errors follow the documented contract.

**Acceptance Scenarios**:

1. **Given** a queued research request, **When** a worker processes it, **Then** the public lifecycle moves through queued/running to a terminal status.
2. **Given** an active event stream, **When** the browser reconnects with a cursor, **Then** only newer persisted events are replayed.
3. **Given** a completed run with evidence, **When** the user opens sources and trace panels, **Then** source previews and deterministic trace summaries are visible without private model reasoning.

---

### User Story 3 - Continue and reuse research context (Priority: P3)

As an analyst, I can ask follow-up questions that refer to prior companies, periods, charts, or evidence without restating all context, while explicit new entities still take precedence.

**Why this priority**: Multi-turn research is needed for realistic analyst workflows and avoids repeated data work.

**Independent Test**: Run a comparison, then ask a follow-up using pronouns or chart references; the system must resolve context safely and reuse exact cached source results only when the request fingerprint matches.

**Acceptance Scenarios**:

1. **Given** a previous answer comparing companies, **When** the user asks "compare their latest revenue growth", **Then** the new run inherits the prior companies and validates a fresh plan.
2. **Given** cached source results from an earlier branch, **When** a later branch has the same canonical request, **Then** the result is reused with current branch binding and calculations rerun.

---

### User Story 4 - Maintain ingestion and analytics readiness (Priority: P4)

As a maintainer, I can ingest SEC filings, SEC Company Facts, investor PDFs, and FRED observations so research runs have reliable document, structured, and macro data available.

**Why this priority**: Research quality depends on complete and provenance-preserving data pipelines.

**Independent Test**: In the Docker dev stack, ingest a known ticker and FRED series, process/index documents, then query cached facts and macro observations without live provider calls for read paths.

**Acceptance Scenarios**:

1. **Given** a known ticker, **When** SEC facts are ingested, **Then** canonical observations retain mapping version, period semantics, units, and duplicate/restatement provenance.
2. **Given** a FRED series and date range, **When** observations are ingested, **Then** missing values, revision dates, source URLs, and units are preserved.
3. **Given** SEC filing or PDF documents, **When** documents are processed and indexed, **Then** chunks retain metadata for filtered retrieval and citation previews.

### Edge Cases

- Unknown, ambiguous, or unsupported companies must lead to clarification or abstention instead of fabricated answers.
- Missing required financial data must produce a safe user-facing explanation.
- Conflicting SEC observations must retain provenance rather than overwrite prior facts.
- Correlation outputs must include a non-causation warning.
- Cancellation, timeout, worker restart, and event-stream reconnect must preserve a safe terminal or resumable state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST classify each user request into qualitative retrieval, structured calculation, macro, chart, follow-up, or hybrid routes.
- **FR-002**: The system MUST resolve companies, tickers, metrics, fiscal periods, filing forms, accessions, and macro series before planning source work.
- **FR-003**: The system MUST prepare required company data before source fetching when data is not already available.
- **FR-004**: The system MUST retrieve filing and PDF evidence with metadata filters and adaptive context budgets for narrative questions.
- **FR-005**: The system MUST query canonical financial facts for deterministic metric questions instead of relying on embedded prose.
- **FR-006**: The system MUST query cached FRED observations for macro questions and preserve revision-aware lineage.
- **FR-007**: The system MUST calculate growth, percentage change, CAGR, margin, rolling average, normalized index, and correlation using deterministic inputs.
- **FR-008**: The system MUST generate chart specifications only from validated numerical datasets with source lineage.
- **FR-009**: The system MUST merge document evidence, financial facts, macro observations, calculations, and charts into evidence envelopes with stable IDs.
- **FR-010**: The system MUST validate draft answers for unsupported claims, unknown citations, wrong company, wrong period, wrong unit, unsupported numbers, unsafe correlation claims, and incomplete calculation lineage.
- **FR-011**: The system MUST repair or abstain when citation validation fails and MUST NOT return citation-invalid draft answers.
- **FR-012**: The system MUST persist research runs, session metadata, source caches, event streams, feedback, cancellation state, and worker leases in PostgreSQL.
- **FR-013**: The system MUST support bounded follow-up context while allowing explicit new companies, metrics, periods, forms, and dates to override inherited context.
- **FR-014**: The system MUST expose research lifecycle, event stream, source preview, run detail, feedback, and company catalog API surfaces under `/api/v1`.
- **FR-015**: The system MUST present answer text, company badges, charts, source previews, trace events, and run history in the web UI.
- **FR-016**: The system MUST keep public traces privacy-safe by excluding raw prompts, provider payloads, hidden reasoning, raw retrieved passages, credentials, stack traces, and draft invalid answers.

### Key Entities *(include if feature involves data)*

- **ResearchRun**: A queued, running, terminal, cancelled, or timed-out research execution tied to a session and question.
- **ResearchSession**: A bounded conversation context with recent messages, active run metadata, source cache entries, and expiry rules.
- **ResolvedQuery**: Normalized companies, tickers, periods, metrics, forms, macro series, follow-up markers, and route signals.
- **ExecutionPlan**: A validated branch plan for retrieval, financial facts, macro series, calculations, charts, and answer generation.
- **EvidenceEnvelope**: A source-backed record with stable ID, kind, summary, source metadata, and optional lineage references.
- **FinancialObservation**: A canonical SEC fact with metric mapping, period semantics, unit, filing provenance, and conflict markers.
- **MacroObservation**: A FRED observation with series metadata, value or missing marker, revision date, source URL, unit, and frequency.
- **ChartArtifact**: A validated chart specification produced from complete, ascending, labelled, lineage-backed data rows.
- **PublicTraceEvent**: A privacy-safe event that describes lifecycle, analysis, entity resolution, plan summary, tool status, validation, chart readiness, answer tokens, or terminal state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For supported financial metric questions with available facts, answers include deterministic calculation evidence and pass citation validation before finalization.
- **SC-002**: For supported narrative filing questions with available indexed documents, answers include document evidence with company and source metadata.
- **SC-003**: For supported chart requests, chart artifacts are generated only when every plotted point has complete numeric data and lineage.
- **SC-004**: A browser can recover an interrupted event stream using the last seen event ID without duplicating already consumed events.
- **SC-005**: A follow-up question can inherit prior companies when no current company is explicit, while an explicit company in the new question always wins.
- **SC-006**: Public API errors use the documented error envelope and do not expose provider, SQL, credential, or stack-trace details.
- **SC-007**: Existing backend and web test suites cover the main baseline areas: agent workflow, research API, retrieval, financial facts, FRED, evidence validation, persistence, chart rendering, source presentation, and event handling.

## Assumptions

- This baseline backlog documents current product capabilities and near-term validation work; it is not a request to rebuild the product from scratch.
- Development database checks use `.env` plus the Docker dev stack, not the local `company_lens.db` file.
- Authentication is intentionally out of scope for the current demo-mode API boundary.
- GitHub issue conversion is deferred until the user chooses which backlog items should become tracked issues.
