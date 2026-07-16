# Graph Report - .  (2026-07-16)

## Corpus Check
- 460 files · ~266,510 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4486 nodes · 12833 edges · 250 communities (207 shown, 43 thin omitted)
- Extraction: 65% EXTRACTED · 35% INFERRED · 0% AMBIGUOUS · INFERRED: 4479 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Research Agent State Flow
- Calculation and Retrieval Branches
- Query and Session Context
- Research Planning Runtime
- Investor PDF Ingestion
- Financial Calculation Engine
- ML Reranker Service
- Document Domain Model
- Company Facts Ingestion
- External Request Resilience
- Research Web Interface
- Evaluation Run Models
- FRED Macro Data
- Project Governance and Delivery
- Golden Evaluation Datasets
- Langfuse Dataset Sync
- Feature Specifications and Prompts
- Operation Reconciliation Flow
- SEC Filing Ingestion
- Data Source Checks
- Evaluation Execution Workflow
- Model Provider Contracts
- Evaluation API Schemas
- Research API Schemas
- Prompt Registry System
- Execution Policy Schemas
- Langfuse Sync Tests
- Research Workflow Readiness
- Research Run Repository
- Adaptive Retrieval Service
- Financial Fact Queries
- Persistent Research Agent
- Follow Up Plan Replay
- Company Entity Resolution
- On Demand Data Preparation
- Langfuse Experiment Runner
- Dataset Selection Schemas
- Retrieval Planning and Resolution
- Baseline Retrieval Service
- SQL Research Tools
- Golden Case Evaluation
- Frontend Dependency Stack
- GitHub Evaluation Reporting
- OpenAI Provider Tests
- Answer Display Formatting
- CLI Configuration and Dispatch
- Research API Endpoints
- Frontend TypeScript Configuration
- OpenAI Research Provider
- Deterministic Evaluation Runner
- Evaluation Result Schemas
- Telemetry and Tracing
- Score Contract Reconciliation
- Evaluation Replay and Manifests
- Evidence Validation System
- Retrieval and Reranking Tests
- Embedding Providers
- Dataset Run Schemas
- Operation Conflict Detection
- Frontend Development Dependencies
- Evaluation Orchestrator
- Evaluation Manifest Schemas
- Document Text Processing
- Execution Artifact Schemas
- Case Result Schemas
- Persistence Agent Tests
- Evaluation Case Schemas
- Question Parsing Workflow
- Application Configuration Tests
- Reranking Contracts
- Claim Validation Pipeline
- Observability Security Tests
- Embedding Indexing Service
- Evaluation Quality Gates
- Dataset Identity Schemas
- Evaluation Execution Records
- Evaluation Artifact Recovery
- Case Observation Mapping
- Node TypeScript Configuration
- Evaluation Component Schemas
- Research Session Output
- Document Processing Tests
- Research Worker Service
- Model Configuration Schemas
- Research Run Models
- Golden Agent Runner
- Evaluation Journal Schemas
- Research State Context
- Research Session Screenshot
- Postgres Research Runtime
- Evaluation Gate Schemas
- Evaluation Artifact Paths
- Spec Kit Shell Utilities
- Research Event Types
- Research Architecture Docs
- Claim Extraction Pipeline
- Evaluation Outcome Schemas
- Session Manager Tests
- Langfuse Prompt Sync
- Agent CLI Tests
- Evaluation Preflight Tests
- Score Definition Schemas
- Evaluation GitHub Tests
- Research Worker Leasing
- Retrieval Benchmark Runner
- Score Binding Schemas
- Answer Output Schemas
- Evaluation Journal Contract
- Fallback Financial Answers
- SEC Section Detection
- Retrieval Architecture Docs
- Evaluation Phase Schemas
- GitHub Reporting Schemas
- Evaluation Command Execution
- Agent Execution Events
- Frontend API Client
- Frontend Domain Types
- Research Chart Rendering
- Structured Logging
- Evaluator Version Schemas
- Semantic Support Judge
- Health Check API
- Company Preparation Queries
- Score Contract Schema
- Evaluation CLI Commands
- Investor PDF Manifest
- Golden Agent Tests
- Research Browser Storage
- Request Body Limits
- FastAPI Application Setup
- Hybrid Research Evaluation
- Score Applicability Schemas
- Project Identity Schemas
- Evaluation Gate Status
- Evaluation Failure Codes
- Input Security Controls
- Core Domain Entities
- Golden Evaluation Operations
- Citation Repair Workflow
- Research Plan Constraints
- Evaluation Metrics
- Reconciliation Outcome Tests
- Frontend Package Scripts
- Financial Metric Mapping
- Synthetic Retrieval Evaluation
- Score Category Schemas
- Reranker API Contract
- Terminal Case Schemas
- Company Data Diagnostics
- Follow Up Company References
- Financial Request Replay
- Financial Metric Loader
- Frontend Package Metadata
- Evaluation Case Identity
- Operation Conflict Model
- Evaluation Category Schemas
- Plan Validation Logic
- Company Mention Parsing
- Structured Output Retry Tests
- Frontend Research Tests
- Spec Kit Task Workflow
- Investor Document Catalog
- Operations and Privacy
- Evidence Scope Planning
- Database Session Utilities
- Public API Errors
- Citation Evaluation Metrics
- OpenAI Embedding Client
- Research Landing Page
- Generated API Types
- Event Stream Hook
- FRED Analytics Design
- Core Domain Migration
- Score Data Types
- Feature Branch Script
- Score List Schemas
- Alembic Environment
- Score Contract Concepts
- Numeric Constraint Schemas
- Frontend Application Entry
- Research Thread Selection
- Reranker Failure Modes
- Capability Aware Preparation
- Database Session Factory
- Checkpoint Tuple Utilities
- MSW Build Policy
- TypeScript Project References
- React Hooks ESLint Plugin
- React Refresh ESLint Plugin
- JSDOM Test Environment
- GitHub Flavored Markdown
- Reranker Package Metadata
- Reranker Test Package
- Spec Prerequisite Script
- Spec Plan Setup Script
- Spec Tasks Setup Script
- Research Agent Interfaces
- API Version Package
- Deterministic Evaluation Compatibility
- Evaluation Dataset Package
- Evidence Validation Package
- Financial Metrics Package
- Backend Package Metadata
- Observability Utilities Package
- Document Processing Package
- Research Orchestration Package
- Retrieval Services Package
- Jest DOM Testing
- Evaluation Test Support
- Test Package Metadata
- Data Checks Import Shim
- Data Source Diagnostics
- Vite Bundler Dependency
- Vite React Plugin
- Vitest Test Runner
- Web Application Documentation
- Vite Build Configuration
- Backend Python Project
- Reranker Python Project
- Reranker Requirements Checklist
- Operation Reconciliation Contract
- Follow Up Remediation Design
- Langfuse Experiment Runner Decision
- Data Check Workflow

## God Nodes (most connected - your core abstractions)
1. `ResolvedQuery` - 165 edges
2. `QuestionAnalysis` - 164 edges
3. `ExecutionPlan` - 151 edges
4. `Settings` - 125 edges
5. `AgentState` - 114 edges
6. `ResearchAgentRuntime` - 114 edges
7. `CalculationBranch` - 94 edges
8. `AdaptiveRetrievalRequest` - 87 edges
9. `FinancialFactsBranch` - 81 edges
10. `SessionMemory` - 78 edges

## Surprising Connections (you probably didn't know these)
- `Execution Plan` --semantically_similar_to--> `Execution Planning Prompt`  [INFERRED] [semantically similar]
  specs/001-current-product-baseline/spec.md → prompts/agent/plan-request.txt
- `test_model_intents_reject_missing_or_inapplicable_scalars()` --calls--> `ModelCalculationIntent`  [INFERRED]
  tests/agent_workflow/test_operation_intents.py → src/company_lens/agent/calculation_intents.py
- `test_metrics_are_normalized_and_unique()` --calls--> `CalculationIntent`  [INFERRED]
  tests/agent_workflow/test_operation_intents.py → src/company_lens/agent/calculation_intents.py
- `test_source_period_is_not_a_calculation_window()` --calls--> `CalculationIntent`  [INFERRED]
  tests/agent_workflow/test_operation_intents.py → src/company_lens/agent/calculation_intents.py
- `test_question_analysis_validates_capabilities_and_safe_reason_codes()` --calls--> `QuestionAnalysis`  [INFERRED]
  tests/test_agent_contracts.py → src/company_lens/agent/schemas.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Spec Kit Feature Delivery Lifecycle** — _agents_skills_speckit_specify_skill_speckit_specify_workflow, _agents_skills_speckit_clarify_skill_speckit_clarify_workflow, _agents_skills_speckit_plan_skill_speckit_plan_workflow, _agents_skills_speckit_tasks_skill_speckit_tasks_workflow, _agents_skills_speckit_analyze_skill_speckit_analyze_workflow, _agents_skills_speckit_implement_skill_speckit_implement_workflow, _agents_skills_speckit_converge_skill_speckit_converge_workflow [INFERRED 0.95]
- **Evidence-Grounded Company Research** — readme_adaptive_retrieval, readme_structured_financial_facts, readme_citation_validation, _specify_memory_constitution_evidence_first_answers, _specify_memory_constitution_deterministic_data_paths, _specify_memory_constitution_source_lineage_and_citation_safety [INFERRED 0.95]
- **CompanyLens Delivery and Evaluation Surfaces** — docker_compose_dev_development_stack, docker_compose_deployment_stack, _github_workflows_ci_ci_workflow, _github_workflows_eval_full_full_llm_evaluation_workflow [INFERRED 0.85]
- **Core Source Lineage Hierarchy** — docs_architecture_core_domain_er_company, docs_architecture_core_domain_er_source_document, docs_architecture_core_domain_er_document_version, docs_architecture_core_domain_er_filing_section, docs_architecture_core_domain_er_document_chunk, docs_architecture_core_domain_er_evidence_record [EXTRACTED 1.00]
- **Bounded Hybrid Research Pipeline** — docs_architecture_adr_0004_langgraph_research_tools_typed_execution_plan, docs_architecture_adr_0004_langgraph_research_tools_parallel_branch_orchestration, docs_portfolio_hybrid_query_walkthrough_typed_evidence_envelopes, docs_portfolio_hybrid_query_walkthrough_citation_validation, docs_portfolio_research_graph_bounded_research_workflow [INFERRED 0.95]
- **Golden Evaluation Contract** — evals_datasets_golden_readme_reviewed_repository_truth, evals_datasets_golden_core_v1_core_golden_dataset, evals_datasets_golden_follow_up_v1_follow_up_golden_dataset, evals_gates_eval_fast_v1_fast_evaluation_gate, evals_gates_eval_full_v1_full_evaluation_gate [INFERRED 0.95]
- **CompanyLens Agent Prompt Pipeline** — prompts_agent_parse_question_question_parsing_prompt, prompts_agent_extract_company_mentions_company_mention_extraction_prompt, prompts_agent_plan_request_execution_planning_prompt, prompts_agent_reconcile_operations_operation_reconciliation_prompt, prompts_agent_generate_answer_grounded_answer_generation_prompt, prompts_agent_semantic_support_judge_semantic_support_judge_prompt, prompts_agent_repair_answer_answer_repair_prompt [INFERRED 0.85]
- **Baseline Evidence Research Flow** — specs_001_current_product_baseline_spec_evidence_first_research, specs_001_current_product_baseline_spec_execution_plan, specs_001_current_product_baseline_spec_evidence_envelope, specs_001_current_product_baseline_spec_public_trace_event, specs_001_current_product_baseline_spec_deterministic_analytics [INFERRED 0.85]
- **ML Reranker Feature Artifacts** — specs_002_ml_reranker_service_plan_ml_reranker_service_plan, specs_002_ml_reranker_service_spec_ml_reranker_service_spec, specs_002_ml_reranker_service_data_model_ml_reranker_data_model, specs_002_ml_reranker_service_quickstart_ml_reranker_service_quickstart, specs_002_ml_reranker_service_tasks_ml_reranker_service_tasks [EXTRACTED 1.00]
- **Langfuse Evaluation Foundation Design Artifacts** — specs_003_langfuse_evaluation_foundation_spec_feature_specification, specs_003_langfuse_evaluation_foundation_plan_implementation_plan, specs_003_langfuse_evaluation_foundation_data_model_langfuse_evaluation_data_model, specs_003_langfuse_evaluation_foundation_research_phase_0_research, specs_003_langfuse_evaluation_foundation_tasks_implementation_tasks, specs_003_langfuse_evaluation_foundation_quickstart_validation_guide [EXTRACTED 1.00]
- **Reproducible Fail-closed Evaluation Flow** — specs_003_langfuse_evaluation_foundation_data_model_langfuse_project_identity, specs_003_langfuse_evaluation_foundation_contracts_langfuse_mapping_snapshot_verification, specs_003_langfuse_evaluation_foundation_data_model_evaluation_run_manifest, specs_003_langfuse_evaluation_foundation_data_model_evaluation_recovery_journal, specs_003_langfuse_evaluation_foundation_contracts_evaluation_cli_run_evaluation, specs_003_langfuse_evaluation_foundation_contracts_manual_workflow_manual_evaluation_workflow [INFERRED 0.95]
- **Typed Operation Reconciliation Flow** — specs_003_langfuse_evaluation_foundation_data_model_calculation_intent, specs_003_langfuse_evaluation_foundation_data_model_effective_calculation_intent, specs_003_langfuse_evaluation_foundation_data_model_operation_conflict, specs_003_langfuse_evaluation_foundation_data_model_branch_operation_decision, specs_003_langfuse_evaluation_foundation_data_model_operation_reconciliation, specs_003_langfuse_evaluation_foundation_operation_reconciliation_remediation_design_operation_reconciliation_remediation, specs_003_langfuse_evaluation_foundation_contracts_operation_reconciliation_operation_reconciliation_contract [EXTRACTED 1.00]
- **Research Execution Workflow** — docs_screenshot_start_turn, docs_screenshot_parse_question, docs_screenshot_rag_only_intent, docs_screenshot_answer_session_context, docs_screenshot_resolve_entities [EXTRACTED 1.00]
- **Grounded Answer Evidence Chain** — docs_screenshot_filing_grounded_research, docs_screenshot_cited_sources, docs_screenshot_item_1_business_overview, docs_screenshot_evidence_limited_answer [INFERRED 0.85]

## Communities (250 total, 43 thin omitted)

### Community 0 - "Research Agent State Flow"
Cohesion: 0.04
Nodes (99): BranchT, P, R, RequestT, _answer_company_details(), answer_company_targets_from_state(), UUID, _string_or_none() (+91 more)

### Community 1 - "Calculation and Retrieval Branches"
Cohesion: 0.07
Nodes (86): CalculationIntent, ModelCalculationIntent, Provider-facing calculation intent with JSON Schema number fields., _branch_summary(), ExecutionBranch, _task_branch(), AgentCapability, AgentErrorCategory (+78 more)

### Community 2 - "Query and Session Context"
Cohesion: 0.06
Nodes (75): answer_company_targets_from_evidence(), AnswerCompanyTarget, SessionMemory, create_initial_agent_state(), UUID, _planning_artifact_context(), _analysis_requests_add_series(), _analysis_requests_comparison() (+67 more)

### Community 3 - "Research Planning Runtime"
Cohesion: 0.10
Nodes (76): CompanyMentionExtraction, ExecutionPlan, ExecutionPolicy, QuestionAnalysis, ResearchAgent, ResearchAgentRuntime, _financial_branch(), _macro_branch() (+68 more)

### Community 4 - "Investor PDF Ingestion"
Cohesion: 0.09
Nodes (52): IngestionFailure, PdfBlock, PdfPage, SourceArtifact, StoredArtifact, InvestorPdfManifestDocument, _build_line_blocks(), _decimal_or_none() (+44 more)

### Community 5 - "Financial Calculation Engine"
Cohesion: 0.08
Nodes (69): CalculationPoint, _deduplicate_annual_observations_for_growth(), _endpoints(), _execute_calculation(), _financial_filing_key(), _latest(), _numeric_series(), date (+61 more)

### Community 6 - "ML Reranker Service"
Cohesion: 0.06
Nodes (49): ModelFactory, create_app(), _error_response(), FastAPI, JSONResponse, _scorer(), ErrorDetail, ErrorResponse (+41 more)

### Community 7 - "Document Domain Model"
Cohesion: 0.11
Nodes (45): DeclarativeBase, Dialect, Base, AliasKind, ChunkEmbedding, CitationRecord, ClaimRecord, CompanyAlias (+37 more)

### Community 8 - "Company Facts Ingestion"
Cohesion: 0.08
Nodes (48): ArtifactKind, Company, CompanyIdentifier, CompanyTicker, DocumentVersionState, Exchange, FinancialFact, IdentifierKind (+40 more)

### Community 9 - "External Request Resilience"
Cohesion: 0.06
Nodes (37): TraceContentPolicy, _find_failed_tickers(), Session, _run_ingest_sec(), build_company_facts_client(), Session, BaseTransport, archive_base_url() (+29 more)

### Community 10 - "Research Web Interface"
Cohesion: 0.06
Nodes (52): AnswerCompany, AnswerCompanyBadges(), AnswerCompanyBadgesProps, companyAccessibleName(), CompanyBadge(), companyLabel(), buildEvidenceCitationTargets(), EvidenceCitationTarget (+44 more)

### Community 11 - "Evaluation Run Models"
Cohesion: 0.17
Nodes (40): ComponentVersions, DatasetSnapshot, EvaluationRunManifest, ExecutionPolicyManifest, GateManifest, LangfuseProjectIdentity, ManifestDataset, ManifestModel (+32 more)

### Community 12 - "FRED Macro Data"
Cohesion: 0.07
Nodes (36): QueryParameter, _missing_fred_series(), FredClient, FredClientError, _mapping(), _optional_datetime(), Any, date (+28 more)

### Community 13 - "Project Governance and Delivery"
Cohesion: 0.05
Nodes (55): Speckit Cross-Artifact Analysis Workflow, Speckit Requirements Checklist Workflow, Speckit Incremental Clarification Workflow, Speckit Constitution Synchronization Workflow, Speckit Append-Only Convergence Workflow, Speckit Checklist-Gated Implementation Workflow, Speckit Research and Design Planning Workflow, Speckit Quality-Validated Specification Workflow (+47 more)

### Community 14 - "Golden Evaluation Datasets"
Cohesion: 0.06
Nodes (35): FollowUpAddition, FollowUpInheritance, _canonical_hash(), _clean_text(), CompanyReplacement, ConversationTurn, ExpectedBehavior, FollowUpExpectation (+27 more)

### Community 15 - "Langfuse Dataset Sync"
Cohesion: 0.08
Nodes (48): canonical_hash(), item_uuid(), map_golden_case(), MappedDatasetItem, Any, score_uuid(), DatasetSyncResult, _existing_items() (+40 more)

### Community 16 - "Feature Specifications and Prompts"
Cohesion: 0.06
Nodes (51): Company Mention Extraction Prompt, Grounded Answer Generation Prompt, Question Parsing Prompt, Execution Planning Prompt, Operation Reconciliation Prompt, Answer Repair Prompt, Semantic Support Judge Prompt, Prompt Manifest (+43 more)

### Community 17 - "Operation Reconciliation Flow"
Cohesion: 0.08
Nodes (39): BranchOperationDecision, domain_calculation_intent(), _FrozenModel, _normalized_metrics(), OperationReconciliation, BaseModel, CalculationOperation, Decimal (+31 more)

### Community 18 - "SEC Filing Ingestion"
Cohesion: 0.10
Nodes (22): IngestionRun, ArtifactStore, Any, Path, SecFilingMetadata, _artifact_kind_for_mime_type(), build_default_options(), _fiscal_period() (+14 more)

### Community 19 - "Data Source Checks"
Cohesion: 0.10
Nodes (38): PdfReader, build_parser(), main(), ArgumentParser, load_companies(), load_fred_series(), Path, _check_series_metadata() (+30 more)

### Community 20 - "Evaluation Execution Workflow"
Cohesion: 0.05
Nodes (49): Langfuse Evaluation Foundation Specification Quality Checklist, Evaluation CLI Contract, recover-evaluation Command, report-evaluation-pr Command, run-evaluation Command, sync-evaluation-datasets Command, Deterministic Dataset Item Identity, Repository to Langfuse Mapping Contract (+41 more)

### Community 21 - "Model Provider Contracts"
Cohesion: 0.10
Nodes (24): ModelMessage, ModelPurpose, BaseModel, OutputT, Protocol, StructuredOutputT, ResearchModelProvider, StructuredModelResult (+16 more)

### Community 22 - "Evaluation API Schemas"
Cohesion: 0.05
Nodes (44): pattern, type, items, items, minItems, type, minLength, type (+36 more)

### Community 23 - "Research API Schemas"
Cohesion: 0.16
Nodes (40): ResearchCitationOutput, ResearchExecutionOutput, AnalysisSummaryEventData, AnswerCompanyOutput, AnswerTokenEventData, ApiModel, CalculationBranchSummary, CalculationToolResultSummary (+32 more)

### Community 24 - "Prompt Registry System"
Cohesion: 0.11
Nodes (31): build_prompt_provider(), _definition_from_manifest_item(), _int_or_none(), LangfusePromptProvider, _load_manifest(), prompt_content_hash(), PromptDefinition, PromptMetadata (+23 more)

### Community 25 - "Execution Policy Schemas"
Cohesion: 0.05
Nodes (42): embedding_model, max_cases_per_dataset, max_concurrency, max_repair_attempts, max_retries_per_node, max_tool_calls, parser, retrieval_index (+34 more)

### Community 26 - "Langfuse Sync Tests"
Cohesion: 0.11
Nodes (21): FakeApi, FakeDataset, FakeDatasetClient, FakeDatasetItem, FakeDatasetRunItem, FakeDatasetRunItemsApi, FakeExperimentItemResult, FakeExperimentResult (+13 more)

### Community 27 - "Research Workflow Readiness"
Cohesion: 0.12
Nodes (35): FinancialDataReadinessStatus, FinancialDataReadiness, ResearchFrame, _build_research_frame(), _company_entity_identity_keys(), _company_target_source(), _company_targets_from_resolved(), _entity_company_id() (+27 more)

### Community 28 - "Research Run Repository"
Cohesion: 0.13
Nodes (19): LiteralInterruption, ResearchEvent, ResearchResult, _active_values(), _answer_chunks(), _aware(), _event_envelope(), datetime (+11 more)

### Community 29 - "Adaptive Retrieval Service"
Cohesion: 0.15
Nodes (27): RerankerTraceStatus, AdaptiveRetrievalService, _apply_filters(), ContextAssembler, _decimal_text(), _is_sufficient(), _non_negative_float_or_none(), _non_negative_int() (+19 more)

### Community 30 - "Financial Fact Queries"
Cohesion: 0.13
Nodes (17): FinancialFactQuery, FinancialFactQueryResult, BaseModel, _financial_observation(), date, Decimal, AnnualSeriesFinancialTools, MixedPeriodFinancialTools (+9 more)

### Community 31 - "Persistent Research Agent"
Cohesion: 0.17
Nodes (15): RunnableConfig, _aware(), _checkpoint_type_allowlist(), _lease_active(), _metadata(), PersistentResearchAgent, datetime, InterruptionReason (+7 more)

### Community 32 - "Follow Up Plan Replay"
Cohesion: 0.10
Nodes (33): _artifact_chart_type(), _artifact_growth_operation(), _fallback_recent_artifact_period_plan(), _period_override(), CalculationOperation, ChartKind, date, _requests_period_override() (+25 more)

### Community 33 - "Company Entity Resolution"
Cohesion: 0.16
Nodes (27): CompanyMentionCandidate, _ambiguous_sec_company_resolution(), _ambiguous_sec_name_matches(), _blocks_name_match(), _blocks_plain_ticker_match(), _clean_company_candidates(), _clear_sec_mention_name_resolution(), _company_label() (+19 more)

### Community 34 - "On Demand Data Preparation"
Cohesion: 0.12
Nodes (19): Protocol, RuntimeError, Provider-neutral data port used by research graph nodes., ResearchToolError, ResearchTools, SessionOperation, CompanyDataPreparationResult, OnDemandCompanyDataPreparer (+11 more)

### Community 35 - "Langfuse Experiment Runner"
Cohesion: 0.13
Nodes (30): _aggregate_scores(), _evaluate_observation(), _infrastructure_record(), _items(), LangfuseExperimentError, _publish_item_scores(), _publish_score(), Any (+22 more)

### Community 36 - "Dataset Selection Schemas"
Cohesion: 0.07
Nodes (34): additionalProperties, minProperties, type, items, minItems, type, uniqueItems, $ref (+26 more)

### Community 37 - "Retrieval Planning and Resolution"
Cohesion: 0.11
Nodes (25): Session, EntityCandidate, RetrievalPlanner, EntityResolver, _fiscal_years(), _normalize(), _normalize_company_name(), date (+17 more)

### Community 38 - "Baseline Retrieval Service"
Cohesion: 0.15
Nodes (10): RetrievalFilters, _apply_filter_conditions(), _Candidate, _matched_filter_payload(), _period_key(), Any, Select, UUID (+2 more)

### Community 39 - "SQL Research Tools"
Cohesion: 0.14
Nodes (19): SQL-backed adapter that owns one short-lived session per call.      LangGraph ca, SqlResearchTools, SecCompany, _FakeSecClient, MonkeyPatch, _sql_tools_with_sec_map(), test_sql_research_tools_blocks_common_chart_word_as_plain_ticker(), test_sql_research_tools_discovers_public_company_from_sec_ticker_map() (+11 more)

### Community 40 - "Golden Case Evaluation"
Cohesion: 0.15
Nodes (23): _check_companies(), _check_metrics(), _check_operation(), _check_prohibited_tools(), _check_required_tools(), _check_route(), evaluate_case(), executed_steps() (+15 more)

### Community 41 - "Frontend Dependency Stack"
Cohesion: 0.06
Nodes (31): @assistant-ui/react, @assistant-ui/react-markdown, clsx, @fontsource/ibm-plex-mono, @fontsource-variable/ibm-plex-sans, @fontsource-variable/newsreader, lucide-react, openapi-fetch (+23 more)

### Community 42 - "GitHub Evaluation Reporting"
Cohesion: 0.11
Nodes (16): LiteralAction, _api_from_environment(), dispatch_github_reporting_command(), Any, Namespace, register_github_reporting_command(), GitHubReportingApi, GitHubReportingError (+8 more)

### Community 43 - "OpenAI Provider Tests"
Cohesion: 0.18
Nodes (26): ModelProviderError, RuntimeError, FakeResponses, _messages(), ParsedIntent, _provider(), Any, BaseModel (+18 more)

### Community 44 - "Answer Display Formatting"
Cohesion: 0.15
Nodes (28): _display_decimal(), _display_value(), _fallback_calculation_period(), _fallback_company_name(), _fallback_decimal(), _fallback_decimal_places(), _fallback_display_value(), _fallback_operation_label() (+20 more)

### Community 45 - "CLI Configuration and Dispatch"
Cohesion: 0.21
Nodes (29): _add_json_options(), _add_research_output_options(), _build_embedder(), _dispatch_command(), main(), _optional_date(), ArgumentParser, date (+21 more)

### Community 46 - "Research API Endpoints"
Cohesion: 0.13
Nodes (27): alias, ge, Header, le, max_length, min_length, Query, ResearchAccepted (+19 more)

### Community 47 - "Frontend TypeScript Configuration"
Cohesion: 0.07
Nodes (29): DOM.Iterable, src, @testing-library/jest-dom, vite/client, vitest/globals, compilerOptions, allowJs, allowSyntheticDefaultImports (+21 more)

### Community 48 - "OpenAI Research Provider"
Cohesion: 0.17
Nodes (26): ResponseInputParam, ModelUsage, build_openai_model_provider(), _error(), _invalid_response_error(), _map_provider_error(), _message_input(), _messages_payload() (+18 more)

### Community 49 - "Deterministic Evaluation Runner"
Cohesion: 0.22
Nodes (27): evaluate_golden_results(), load_observed_results(), Path, follow_up_results(), Any, test_follow_up_company_rules_accept_ticker_only_mentions(), test_follow_up_dataset_defines_operations_to_inherit(), _core_results() (+19 more)

### Community 50 - "Evaluation Result Schemas"
Cohesion: 0.10
Nodes (29): null, string, type, format, type, type, type, format (+21 more)

### Community 51 - "Telemetry and Tracing"
Cohesion: 0.14
Nodes (28): Span, _append_model_usage_record(), bind_embedding_observation(), configure_telemetry(), _content_payload(), current_embedding_observation(), EmbeddingObservationContext, _initialize_instruments() (+20 more)

### Community 52 - "Score Contract Reconciliation"
Cohesion: 0.17
Nodes (20): _compatible(), _create_score_config(), _list_score_configs(), Any, RuntimeError, reconcile_score_configs(), ScoreConfigError, _value() (+12 more)

### Community 53 - "Evaluation Replay and Manifests"
Cohesion: 0.13
Nodes (25): ReconciledScoreConfigs, build_evaluation_manifest(), _file_hash(), _manifest_dataset(), _model_configs(), Path, UUID, manifest_fingerprint() (+17 more)

### Community 54 - "Evidence Validation System"
Cohesion: 0.20
Nodes (24): EvidenceRegistry, Immutable-by-convention registry for evidence assembled for one answer., EvidenceMetadata, AnswerValidator, _fact(), UUID, test_calculated_claim_requires_complete_input_lineage(), test_calculation_formula_constants_and_company_metadata_support_claim() (+16 more)

### Community 55 - "Retrieval and Reranking Tests"
Cohesion: 0.21
Nodes (26): HttpReranker, RetrievalRequest, _patch_http_client(), CaptureFixture, MonkeyPatch, Request, Response, Session (+18 more)

### Community 56 - "Embedding Providers"
Cohesion: 0.10
Nodes (18): EmbeddingProvider, build_embedder(), cosine_similarity(), Embedder, EmbeddingInputTooLongError, LocalFeatureHashingEmbedder, OpenAIEmbedder, Protocol (+10 more)

### Community 57 - "Dataset Run Schemas"
Cohesion: 0.07
Nodes (28): type, items, type, minLength, type, minimum, type, additionalProperties (+20 more)

### Community 58 - "Operation Conflict Detection"
Cohesion: 0.21
Nodes (26): _detect_operation_conflict(), _effective_calculation_intents(), EffectiveCalculationIntent, _intent_semantics(), _intents_from_final_plan(), _metric_compatible(), _metric_tokens(), _metrics_compatible() (+18 more)

### Community 59 - "Frontend Development Dependencies"
Cohesion: 0.07
Nodes (27): eslint, @eslint/js, globals, msw, openapi-typescript, @playwright/test, @tailwindcss/vite, @testing-library/react (+19 more)

### Community 60 - "Evaluation Orchestrator"
Cohesion: 0.22
Nodes (23): AbstractContextManager, run_evaluation(), _json(), Path, test_generated_execution_and_journal_validate_against_public_contracts(), test_repository_score_contract_validates_against_schema(), _agent_provider(), PassingAgent (+15 more)

### Community 61 - "Evaluation Manifest Schemas"
Cohesion: 0.08
Nodes (26): actor, run_url, $defs, manifest, promptVersion, reasonCodes, scoreContractManifest, sha256 (+18 more)

### Community 62 - "Document Text Processing"
Cohesion: 0.16
Nodes (22): _decode_bytes(), decode_document_content(), estimate_token_count(), fixed_token_chunks(), _flush_semantic_chunk(), _has_signal(), jaccard(), looks_like_boilerplate() (+14 more)

### Community 63 - "Execution Artifact Schemas"
Cohesion: 0.08
Nodes (25): artifact_paths, commit_sha, completed_at, datasets, environment, execution_policy, gate, manifest_fingerprint (+17 more)

### Community 64 - "Case Result Schemas"
Cohesion: 0.08
Nodes (25): category, checks, mismatched, unavailable, verified, additionalProperties, required, type (+17 more)

### Community 65 - "Persistence Agent Tests"
Cohesion: 0.36
Nodes (20): InMemorySaver, JsonPlusSerializer, checkpoint_serializer(), ResearchSessionRepository, _agent(), _analysis(), _answer(), CountingTools (+12 more)

### Community 66 - "Evaluation Case Schemas"
Cohesion: 0.09
Nodes (23): number, maximum, minimum, type, additionalProperties, minLength, type, properties (+15 more)

### Community 67 - "Question Parsing Workflow"
Cohesion: 0.15
Nodes (18): ModelQuestionAnalysis, Permissive model boundary before domain invariant normalization., _comparison_parts(), _comparison_target(), _latest_user_question(), _looks_like_incomplete_comparison(), _parse_failure_answer(), _suggested_query_rewrites() (+10 more)

### Community 68 - "Application Configuration Tests"
Cohesion: 0.11
Nodes (15): BaseSettings, Settings, MonkeyPatch, test_missing_application_schema_has_safe_actionable_error(), test_production_agent_assembly_uses_openai_embedder_and_configured_index(), test_semantic_judge_defaults_to_appeal_only(), test_setup_checks_application_schema_before_checkpoint_setup(), test_langfuse_project_id_uses_explicit_evaluation_setting() (+7 more)

### Community 69 - "Reranking Contracts"
Cohesion: 0.17
Nodes (16): _fill_missing_outputs(), NoopReranker, _parse_response(), Any, Protocol, RuntimeError, Sanitized reranker failure used for fail-closed retrieval mode., Return replacement scores for the input items. (+8 more)

### Community 70 - "Claim Validation Pipeline"
Cohesion: 0.23
Nodes (16): SemanticSupportJudge, ClaimRecord, SemanticSupportResult, ValidationIssue, _call_semantic_judge(), _claim_numbers(), _contains_token(), _decimal() (+8 more)

### Community 71 - "Observability Security Tests"
Cohesion: 0.19
Nodes (17): record_operation_reconciliation(), record_generation(), _disable_generation_metrics(), _disable_operation_metrics(), _FakeReadableSpan, _FakeSpan, test_embedding_observation_records_usage_without_static_cost(), test_generation_observation_records_trace_tags() (+9 more)

### Community 72 - "Embedding Indexing Service"
Cohesion: 0.21
Nodes (11): EmbeddingIndex, _embedding_tags(), EmbeddingIndexingService, EmbeddingFailure, EmbeddingIndexingRequest, EmbeddingIndexingResult, BaseModel, RetrievalDiagnostics (+3 more)

### Community 73 - "Evaluation Quality Gates"
Cohesion: 0.16
Nodes (16): evaluate_gate(), EvaluationGate, EvaluationGateFailure, EvaluationGateResult, load_evaluation_gate(), OperationalBudget, Path, _check_maximum() (+8 more)

### Community 74 - "Dataset Identity Schemas"
Cohesion: 0.12
Nodes (21): active_item_hashes, active_item_ids, aggregate_scores, case_results, dataset_version, langfuse_dataset_id, langfuse_dataset_run_id, langfuse_project_id (+13 more)

### Community 75 - "Evaluation Execution Records"
Cohesion: 0.10
Nodes (20): additionalProperties, allOf, format, type, format, type, $id, $ref (+12 more)

### Community 76 - "Evaluation Artifact Recovery"
Cohesion: 0.18
Nodes (18): format_execution_summary(), _guard_forbidden_keys(), materialize_execution_artifacts(), Path, recover_evaluation_artifacts(), execute_preflighted_evaluation(), AbstractContextManager, Any (+10 more)

### Community 77 - "Case Observation Mapping"
Cohesion: 0.23
Nodes (18): ExpectedRoute, case_observation_from_state(), _citation_observation(), _has_unresolved_company_target(), _observed_companies(), _observed_operation(), observed_result_from_state(), _observed_route() (+10 more)

### Community 78 - "Node TypeScript Configuration"
Cohesion: 0.10
Nodes (19): e2e, eslint.config.js, playwright.config.ts, vite.config.ts, compilerOptions, allowImportingTsExtensions, lib, module (+11 more)

### Community 79 - "Evaluation Component Schemas"
Cohesion: 0.13
Nodes (20): type, $ref, properties, minLength, type, properties, config_bindings, content_hash (+12 more)

### Community 80 - "Research Session Output"
Cohesion: 0.22
Nodes (14): OutputModel, BaseModel, research_run_output(), research_session_output(), ResearchErrorDetail, ResearchErrorOutput, ResearchOperationOutput, ResearchRunOutput (+6 more)

### Community 81 - "Document Processing Tests"
Cohesion: 0.21
Nodes (17): corpus_stats(), _count(), demo_chunks(), _documents_by_kind(), _preview(), Any, Session, _rate() (+9 more)

### Community 82 - "Research Worker Service"
Cohesion: 0.20
Nodes (14): StartResearchRequest, ResearchWorker, _completed_state(), InterruptionReason, sessionmaker, UUID, _repository(), _repository_with_factory() (+6 more)

### Community 83 - "Model Configuration Schemas"
Cohesion: 0.11
Nodes (19): answer, high, low, medium, none, planning, repair, xhigh (+11 more)

### Community 84 - "Research Run Models"
Cohesion: 0.25
Nodes (15): install_error_handlers(), PublicApiError, RuntimeError, RateLimitBucket, ResearchEvent, ResearchFeedback, ResearchRun, ActiveResearchRunError (+7 more)

### Community 85 - "Golden Agent Runner"
Cohesion: 0.22
Nodes (17): _case_attempt_limit(), _case_attempt_session_id(), _case_session_id(), _elapsed_ms(), GoldenResearchAgent, _has_provider_execution_failure(), _model_usage_totals(), _node_name() (+9 more)

### Community 86 - "Evaluation Journal Schemas"
Cohesion: 0.11
Nodes (18): format, type, anyOf, anyOf, properties, execution_id, manifest, project_identity (+10 more)

### Community 87 - "Research State Context"
Cohesion: 0.17
Nodes (16): activeRunFor(), ConnectionState, EvidenceFocus, latestRunFor(), latestRunTimestamp(), mergeSelectedRun(), queryKeys, ResearchContext (+8 more)

### Community 88 - "Research Session Screenshot"
Cohesion: 0.17
Nodes (17): Answer Session Context, Cited Filing Sources, Transition from On-Premises Technology to Cloud Services, Cloudflare, Inc., CompanyLens Research Session, Competitive Risk Disclosure, Connectivity Cloud, Evidence-Limited Answer (+9 more)

### Community 89 - "Postgres Research Runtime"
Cohesion: 0.18
Nodes (16): PostgresSaver, open_persistent_research_agent(), open_research_session_manager(), RuntimeError, Safe configuration failure suitable for application and CLI boundaries., Initialize LangGraph-owned tables after the application migration is present., Open persistence-only session controls without constructing OpenAI clients., Assemble the production OpenAI, SQL, and PostgreSQL research stack. (+8 more)

### Community 90 - "Evaluation Gate Schemas"
Cohesion: 0.15
Nodes (17): config_bindings, config_status, content_hash, max_output_tokens, purpose, reasoning_effort, source, source_path (+9 more)

### Community 91 - "Evaluation Artifact Paths"
Cohesion: 0.12
Nodes (17): journal, json, markdown, additionalProperties, properties, required, type, minLength (+9 more)

### Community 92 - "Spec Kit Shell Utilities"
Cohesion: 0.13
Nodes (5): get_feature_paths(), get_repo_root(), _persist_feature_json(), resolve_specify_init_dir(), common.sh script

### Community 93 - "Research Event Types"
Cohesion: 0.12
Nodes (16): analysisEvent, answerEvent, branchSchema, chartEvent, entitiesEvent, eventBase, nodeEvent, planEvent (+8 more)

### Community 94 - "Research Architecture Docs"
Cohesion: 0.16
Nodes (16): ADR 0004 Stateless LangGraph Workflow and Research Tools Port, Parallel Source Branch Orchestration, ResearchTools Protocol, Validated Typed Execution Plan, ADR 0005 Persistent Research Sessions and Checkpoints, PostgreSQL LangGraph Checkpoints, Leased Research Session Lifecycle, Exact Typed Request Session Cache (+8 more)

### Community 95 - "Claim Extraction Pipeline"
Cohesion: 0.20
Nodes (15): Match, _claim_segments(), extract_claims(), _is_generic_structural_label(), _is_mergeable_structural_fragment(), _is_structural_fragment(), _is_table_row(), _merge_structural_fragments() (+7 more)

### Community 96 - "Evaluation Outcome Schemas"
Cohesion: 0.12
Nodes (16): dataset_runs, phase, reporting_failure_codes, reporting_status, reporting_target, sequence, terminal_cases, updated_at (+8 more)

### Community 97 - "Session Manager Tests"
Cohesion: 0.17
Nodes (9): build_persistent_research_agent(), BaseCheckpointSaver, CompiledStateGraph, timedelta, Manage persisted research sessions without requiring model or tool providers., ResearchSessionManager, SessionErrorCode, NoDataTools (+1 more)

### Community 98 - "Langfuse Prompt Sync"
Cohesion: 0.18
Nodes (12): _int_or_none(), main(), PromptSyncError, PromptSyncResult, Any, BaseModel, RuntimeError, sync_prompts_to_langfuse() (+4 more)

### Community 99 - "Agent CLI Tests"
Cohesion: 0.30
Nodes (12): _completed_state(), _context_value(), FakeAgent, Any, CaptureFixture, MonkeyPatch, test_research_configuration_error_does_not_expose_exception_text(), test_research_failed_state_returns_one_and_compact_summary() (+4 more)

### Community 100 - "Evaluation Preflight Tests"
Cohesion: 0.19
Nodes (10): FailureClient, _agent_provider(), DatasetReadFailureClient, NeverCalledAgent, Any, Exception, Path, ScoreConfigFailureClient (+2 more)

### Community 101 - "Score Definition Schemas"
Cohesion: 0.13
Nodes (15): item, run, minLength, type, minLength, type, maximum, minimum (+7 more)

### Community 102 - "Evaluation GitHub Tests"
Cohesion: 0.28
Nodes (10): IssueComment, EvaluationRequest, _args(), _artifacts(), FakeGitHubApi, Namespace, Path, test_duplicate_canonical_comments_fail_reporting_without_changing_execution() (+2 more)

### Community 103 - "Research Worker Leasing"
Cohesion: 0.18
Nodes (7): _interruption_message(), _interruption_status(), _LeaseHeartbeat, _public_status(), ResearchRun, timedelta, UUID

### Community 104 - "Retrieval Benchmark Runner"
Cohesion: 0.27
Nodes (14): _average(), _duplicate_rate(), _evaluate(), print_benchmark_report(), Any, Path, Session, _result_chunk_keys() (+6 more)

### Community 105 - "Score Binding Schemas"
Cohesion: 0.14
Nodes (14): langfuse_config_id, score_name, scoreConfigBinding, minLength, type, langfuse_config_id, score_name, maxLength (+6 more)

### Community 106 - "Answer Output Schemas"
Cohesion: 0.19
Nodes (10): SourceChecker, AnswerValidation, ClaimRecord, ClaimValidation, EvidenceKind, FrozenModel, BaseModel, SemanticSupportStatus (+2 more)

### Community 107 - "Evaluation Journal Contract"
Cohesion: 0.14
Nodes (13): additionalProperties, allOf, additionalProperties, required, type, $defs, caseIdentity, $id (+5 more)

### Community 108 - "Fallback Financial Answers"
Cohesion: 0.27
Nodes (8): _deterministic_fallback_answer(), _fallback_financial_fact_table(), _fallback_financial_facts(), _fallback_period_value(), _fallback_financial_fact_cell(), _fallback_multi_company_financial_fact_table(), _fallback_sentences(), EvidenceEnvelope

### Community 109 - "SEC Section Detection"
Cohesion: 0.21
Nodes (8): _best_section_match(), _decode_content(), detect_high_value_sections(), DetectedSection, _looks_like_html(), HTMLParser, Pattern, _TextExtractor

### Community 110 - "Retrieval Architecture Docs"
Cohesion: 0.18
Nodes (13): ADR 0001 Core Domain Hierarchy and Source Lineage, Hierarchical Relational Document Model, Exact Source Lineage, ADR 0002 Baseline Dense Lexical and Hybrid Retrieval, Document Chunk Baseline Retrieval, Reciprocal Rank Fusion, ADR 0003 Exact Entity Resolution and Adaptive Hierarchical Retrieval, Exact Entity Resolution (+5 more)

### Community 111 - "Evaluation Phase Schemas"
Cohesion: 0.15
Nodes (13): initialized, preflighted, project_verified, reporting, running, terminal, completed, errored (+5 more)

### Community 112 - "GitHub Reporting Schemas"
Cohesion: 0.15
Nodes (13): pr_number, repository, reportingTarget, minimum, type, pr_number, repository, additionalProperties (+5 more)

### Community 113 - "Evaluation Command Execution"
Cohesion: 0.35
Nodes (12): Signals, dispatch_execution_command(), _install_signal_handlers(), _print_error(), AbstractContextManager, Any, Namespace, _recover() (+4 more)

### Community 114 - "Agent Execution Events"
Cohesion: 0.31
Nodes (12): AgentExecutionEvent, project_agent_transition(), _result_summary(), _safe_warnings(), _stable_key(), _started_summary(), task_finished_event(), task_started_event() (+4 more)

### Community 115 - "Frontend API Client"
Cohesion: 0.26
Nodes (11): api, ApiError, cancelResearch(), errorMessage(), getResearch(), getSources(), listCompanies(), listResearchRuns() (+3 more)

### Community 116 - "Frontend Domain Types"
Cohesion: 0.15
Nodes (11): ChartSpecification, Company, FeedbackRating, ResearchAccepted, ResearchCitation, ResearchResult, ResearchRun, ResearchRunList (+3 more)

### Community 117 - "Research Chart Rendering"
Cohesion: 0.31
Nodes (10): colors, ResearchChart(), Series(), chart, chartData(), ChartSeriesItem, displaySeriesLabel(), formatChartValue() (+2 more)

### Community 118 - "Structured Logging"
Cohesion: 0.29
Nodes (9): LogRecord, bind_context(), current_context(), ObservabilityContext, UUID, configure_logging(), JsonFormatter, _redact() (+1 more)

### Community 119 - "Evaluator Version Schemas"
Cohesion: 0.17
Nodes (12): minLength, type, maxLength, minLength, pattern, type, properties, evaluator_version (+4 more)

### Community 120 - "Semantic Support Judge"
Cohesion: 0.27
Nodes (9): ModelSemanticSupportJudge, BaseModel, Optional semantic support check used after deterministic validation passes., SemanticSupportJudgment, JudgeProvider, test_model_semantic_support_judge_distinguishes_unsupported_and_unavailable(), test_model_semantic_support_judge_passes_validation_issues(), test_model_semantic_support_judge_skips_structured_evidence() (+1 more)

### Community 121 - "Health Check API"
Cohesion: 0.21
Nodes (9): health(), Depends, JSONResponse, Request, check_database(), DatabaseHealth, ComponentHealth, HealthResponse (+1 more)

### Community 122 - "Company Preparation Queries"
Cohesion: 0.41
Nodes (11): company_data_is_ready(), company_for_ticker(), current_sec_document_version_ids(), financial_fact_count(), indexed_chunk_count(), Company, Session, sessionmaker (+3 more)

### Community 123 - "Score Contract Schema"
Cohesion: 0.18
Nodes (10): additionalProperties, $defs, score, $id, $schema, additionalProperties, allOf, type (+2 more)

### Community 124 - "Evaluation CLI Commands"
Cohesion: 0.35
Nodes (9): dispatch_evaluation_command(), AbstractContextManager, Any, Namespace, register_evaluation_commands(), _run_evaluate_golden_results(), _run_golden_agent(), _run_validate_golden_dataset() (+1 more)

### Community 125 - "Investor PDF Manifest"
Cohesion: 0.31
Nodes (10): load_investor_pdf_manifest(), _normalize_cik(), _optional_date(), _optional_int(), _optional_str(), _parse_document(), Any, date (+2 more)

### Community 126 - "Golden Agent Tests"
Cohesion: 0.24
Nodes (9): _context_value(), FakeGoldenAgent, Any, CaptureFixture, MonkeyPatch, Path, test_golden_agent_runner_captures_sanitized_infrastructure_outcome(), test_golden_agent_runner_executes_follow_up_turns_in_one_session() (+1 more)

### Community 127 - "Research Browser Storage"
Cohesion: 0.40
Nodes (8): isStoredResearch(), loadResearchIndex(), readResearchIndex(), researchTitleFromQuestion(), sortResearchIndex(), StoredResearchInput, upsertResearchIndex(), writeResearchIndex()

### Community 128 - "Request Body Limits"
Cohesion: 0.27
Nodes (7): ASGIApp, Receive, Scope, BodySizeLimitMiddleware, Send, _send_too_large(), _too_large()

### Community 129 - "FastAPI Application Setup"
Cohesion: 0.22
Nodes (7): BaseHTTPMiddleware, create_app(), FastAPI, CorrelationIdMiddleware, Request, Response, instrument_fastapi()

### Community 130 - "Hybrid Research Evaluation"
Cohesion: 0.22
Nodes (10): Finite Evidence Recovery Sequence, Bounded Adaptive Retrieval Plan, Citation and Lineage Validation, Hybrid Query Walkthrough, Hybrid Research Query, Citation Integrity Challenge Scenarios, CompanyLens Core Golden Dataset v1, Hybrid Facts and Narrative Route (+2 more)

### Community 131 - "Score Applicability Schemas"
Cohesion: 0.20
Nodes (10): applicability, data_type, description, evaluator_version, scope, name, scores, version (+2 more)

### Community 132 - "Project Identity Schemas"
Cohesion: 0.20
Nodes (10): checked_at, expected_project_id, resolved_project_id, resolved_project_name, projectIdentity, status, additionalProperties, allOf (+2 more)

### Community 133 - "Evaluation Gate Status"
Cohesion: 0.22
Nodes (10): not_requested, pending, succeeded, enum, failed, not_evaluated, passed, gate_status (+2 more)

### Community 134 - "Evaluation Failure Codes"
Cohesion: 0.22
Nodes (10): items, type, uniqueItems, pattern, type, failure_codes, reporting_failure_codes, items (+2 more)

### Community 135 - "Input Security Controls"
Cohesion: 0.27
Nodes (7): prompt_injection_flags(), ValueError, sanitize_untrusted_text(), UnsafeUrlError, test_outbound_allowlist_rejects_credentials_private_hosts_and_unknown_domains(), test_sec_html_extraction_discards_executable_and_style_content(), test_untrusted_document_text_is_sanitized_and_flagged()

### Community 136 - "Core Domain Entities"
Cohesion: 0.31
Nodes (9): ChunkEmbedding, Company, DocumentChunk, DocumentVersion, EvidenceRecord, FilingSection, FinancialFact, SourceDocument (+1 more)

### Community 137 - "Golden Evaluation Operations"
Cohesion: 0.25
Nodes (9): Evaluation Operations, CompanyLens Follow-Up Golden Dataset v1, Golden Evaluation Datasets, Deterministic Langfuse Dataset Synchronization, Reviewed Repository Evaluation Truth, Fast Evaluation Gate v1, Strict Deterministic Evaluation Thresholds, Full Evaluation Gate v1 (+1 more)

### Community 138 - "Citation Repair Workflow"
Cohesion: 0.39
Nodes (8): _citation_fallback_update(), _citation_repair_exhausted_update(), _citation_repair_failure_answer(), Runtime, _repair_or_abstain(), _validate_citations(), CitationReference, record_validation()

### Community 139 - "Research Plan Constraints"
Cohesion: 0.33
Nodes (8): _allowed_source_capabilities(), _constrain_plan_sources(), _explicit_document_research(), _must_remain_unsupported(), _plan_branch_references(), ExecutionBranch, Remove model-added source kinds that the classified request did not authorize., _unique_growth_branch_id()

### Community 140 - "Evaluation Metrics"
Cohesion: 0.42
Nodes (7): evaluate_dataset(), _validate_dataset_identity(), category_evaluations(), _check_ratio(), evaluation_metrics(), missing_results(), _ratio()

### Community 141 - "Reconciliation Outcome Tests"
Cohesion: 0.53
Nodes (7): _agent_provider(), Path, _request(), _settings(), TerminalReconciliationAgent, test_provider_reconciliation_failure_is_not_evaluated_infrastructure(), test_semantic_reconciliation_failure_is_an_observed_quality_failure()

### Community 142 - "Frontend Package Scripts"
Cohesion: 0.22
Nodes (9): scripts, api:generate, build, dev, lint, test, test:e2e, test:watch (+1 more)

### Community 143 - "Financial Metric Mapping"
Cohesion: 0.29
Nodes (8): SEC Company Facts Canonical Metric Mapping v1, Canonical Financial Metrics, Issuer-Specific Metric Overrides, Canonical Financial Metrics, Conflict-Preserving Financial Provenance, Financial Observation Period Semantics, Structured Financial Fact Querying, Structured-Only Financial Route

### Community 144 - "Synthetic Retrieval Evaluation"
Cohesion: 0.29
Nodes (8): Cloudflare 2024 Form 10-K, Cloudflare 2025 Form 10-K, Retrieval Query Expectations, Synthetic Company Retrieval v1, Deterministic Evaluation Gate, CompanyLens Foundation Score Contract, Retrieval Quality Categories, Reranking Benchmark Comparison

### Community 145 - "Score Category Schemas"
Cohesion: 0.25
Nodes (8): always, citation_required, follow_up, operational_metrics, prohibited_tools, required_tools, enum, applicability

### Community 146 - "Reranker API Contract"
Cohesion: 0.29
Nodes (8): Backend Reranker Configuration Contract, Reranker Health Operation, CompanyLens Internal Reranker Service, Reranker Readiness Operation, Rerank Operation, Rerank Request, Rerank Response, Optional ML Reranker Docker Profile

### Community 147 - "Terminal Case Schemas"
Cohesion: 0.25
Nodes (8): items, type, $ref, dataset_runs, terminal_cases, items, type, uniqueItems

### Community 148 - "Company Data Diagnostics"
Cohesion: 0.25
Nodes (8): Deterministic Follow-up Inherit Replace Extend Merge, Deterministic Local Ticker Resolution, Per-company Follow-up Provenance, Company Data Check Universe, Company PDF Manifest, FRED Series Manifest, CompanyLens Data Source Checks, Data Check Python Dependencies

### Community 149 - "Follow Up Company References"
Cohesion: 0.46
Nodes (7): _clean_company_reference_term(), _company_identity(), _company_reference_terms(), _contains_reference_term(), _mentions_multiple_recent_companies(), UUID, _references_multiple_prior_companies()

### Community 150 - "Financial Request Replay"
Cohesion: 0.46
Nodes (7): _financial_source_period(), CalculationOperation, date, UUID, _replayed_financial_request(), _replayed_macro_branches(), _same_day_previous_year()

### Community 151 - "Financial Metric Loader"
Cohesion: 0.39
Nodes (7): load_metric_mapping(), Any, Path, _required_string(), _taxonomy_concepts(), _validate_unique(), test_fixture_parser_classifies_periods_and_skips_missing_values()

### Community 152 - "Frontend Package Metadata"
Cohesion: 0.25
Nodes (7): engines, node, name, packageManager, private, type, version

### Community 153 - "Evaluation Case Identity"
Cohesion: 0.29
Nodes (7): minLength, type, properties, minLength, type, case_id, dataset_name

### Community 154 - "Operation Conflict Model"
Cohesion: 0.29
Nodes (7): Operation Reconciliation Failure Contract, CalculationIntent, EffectiveCalculationIntent, OperationConflict, Operation Reconciliation Failure Taxonomy, Structured Operation Conflict Detection, Typed Calculation Intent Resolution

### Community 155 - "Evaluation Category Schemas"
Cohesion: 0.29
Nodes (7): items, minItems, type, uniqueItems, minLength, type, categories

### Community 156 - "Plan Validation Logic"
Cohesion: 0.29
Nodes (3): _is_reason_code(), ExecutionBranch, _validate_acyclic_dependencies()

### Community 157 - "Company Mention Parsing"
Cohesion: 0.62
Nodes (6): _explicit_company_mention(), _explicit_company_mentions_from_extraction(), _explicit_prefix_in_question(), _normalized_company_phrase(), _phrase_in_question(), _ticker_in_question()

### Community 158 - "Structured Output Retry Tests"
Cohesion: 0.38
Nodes (4): InvalidThenValidResponses, Any, SimpleNamespace, test_invalid_structured_output_is_retried_by_the_workflow()

### Community 160 - "Frontend Research Tests"
Cohesion: 0.29
Nodes (6): chart, citation, cloudflareCompany, execution, MockRun, source

### Community 161 - "Spec Kit Task Workflow"
Cohesion: 0.33
Nodes (6): Feature Design Artifacts, Independent User Story Delivery, Feature Implementation Tasks Template, Spec Kit Core Commands, Full SDD Cycle, Specification and Plan Review Gates

### Community 162 - "Investor Document Catalog"
Cohesion: 0.33
Nodes (6): Cloudflare Q4 2025 Investor Presentation, Datadog 2024 Annual Report, Elastic Fiscal 2025 Annual Report, Investor PDF Document Catalog, MongoDB Fiscal 2024 Annual Report, Snowflake Q4 Fiscal 2025 Investor Presentation

### Community 163 - "Operations and Privacy"
Cohesion: 0.40
Nodes (6): OpenTelemetry and Langfuse Observability, Observability Reliability and Security Operations, External Dependency Reliability Policy, Research and Ingestion Security Controls, Trace Content Privacy Policy, Public Trace Privacy Boundary

### Community 164 - "Evidence Scope Planning"
Cohesion: 0.40
Nodes (4): EvidenceScope, _budget(), RetrievalStrategy, _section_codes()

### Community 165 - "Database Session Utilities"
Cohesion: 0.33
Nodes (3): ResultT, Session, sessionmaker

### Community 166 - "Public API Errors"
Cohesion: 0.53
Nodes (5): public_error_response(), FastAPI, JSONResponse, Request, _response()

### Community 167 - "Citation Evaluation Metrics"
Cohesion: 0.40
Nodes (5): citation_metrics(), CitationMetrics, BaseModel, Compute claim/evidence citation precision and recall., test_citation_precision_and_recall_are_computed_per_claim_evidence_link()

### Community 168 - "OpenAI Embedding Client"
Cohesion: 0.40
Nodes (5): _embedding_input_tokens(), Any, Exception, _response_model(), _retryable_openai_error()

### Community 169 - "Research Landing Page"
Cohesion: 0.47
Nodes (6): CompanyLens Research Page, Evidence-First Public-Company Research, Inspectable Agent Execution, Main TypeScript React Entrypoint, Root Application Mount Point, Warm Theme Color

### Community 170 - "Generated API Types"
Cohesion: 0.33
Nodes (5): components, $defs, operations, paths, webhooks

### Community 171 - "Event Stream Hook"
Cohesion: 0.40
Nodes (5): useEventStream(), hasTerminalEvent(), parseResearchEvent(), loadTrace(), storeTrace()

### Community 172 - "FRED Analytics Design"
Cohesion: 0.40
Nodes (5): SqlResearchTools Adapter, Deterministic Decimal Calculations, FRED Macro Data and Deterministic Analytics, Revision-Aware FRED Cache, Validated Chart Dataset

### Community 174 - "Score Data Types"
Cohesion: 0.40
Nodes (5): CATEGORICAL, NUMERIC, enum, BOOLEAN, data_type

### Community 176 - "Score List Schemas"
Cohesion: 0.40
Nodes (5): $ref, scores, items, minItems, type

### Community 177 - "Alembic Environment"
Cohesion: 0.83
Nodes (3): get_url(), run_migrations_offline(), run_migrations_online()

### Community 178 - "Score Contract Concepts"
Cohesion: 0.50
Nodes (4): Foundation Score Mapping, ScoreConfigBinding, ScoreContract, ScoreDefinition

### Community 179 - "Numeric Constraint Schemas"
Cohesion: 0.50
Nodes (4): maximum, minimum, type, minimum

### Community 194 - "Reranker Failure Modes"
Cohesion: 0.67
Nodes (3): Graceful Reranker Fallback Mode, Reranker Diagnostics Contract, Strict Reranker Failure Mode

### Community 195 - "Capability Aware Preparation"
Cohesion: 0.67
Nodes (3): CompanyDataPreparationRequirements, Capability-aware Company Preparation, Capability-aware Preparation Decision

### Community 197 - "Checkpoint Tuple Utilities"
Cohesion: 0.67
Nodes (3): append_tuple(), ItemT, Append checkpointed collection values while restoring tuple immutability.

### Community 198 - "MSW Build Policy"
Cohesion: 1.00
Nodes (3): Allowed Dependency Builds Policy, Disabled MSW Dependency Build, Mock Service Worker

## Knowledge Gaps
- **582 isolated node(s):** `check-prerequisites.sh script`, `common.sh script`, `create-new-feature.sh script`, `setup-plan.sh script`, `setup-tasks.sh script` (+577 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **43 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Application Configuration Tests` to `Investor PDF Ingestion`, `Company Facts Ingestion`, `External Request Resilience`, `Reconciliation Outcome Tests`, `Langfuse Dataset Sync`, `SEC Filing Ingestion`, `Langfuse Sync Tests`, `Persistent Research Agent`, `Company Entity Resolution`, `On Demand Data Preparation`, `Database Session Utilities`, `SQL Research Tools`, `CLI Configuration and Dispatch`, `Research API Endpoints`, `OpenAI Research Provider`, `Telemetry and Tracing`, `Evaluation Replay and Manifests`, `Retrieval and Reranking Tests`, `Evaluation Orchestrator`, `Persistence Agent Tests`, `Reranking Contracts`, `Research Session Output`, `Document Processing Tests`, `Golden Agent Runner`, `Postgres Research Runtime`, `Session Manager Tests`, `Langfuse Prompt Sync`, `Agent CLI Tests`, `Evaluation Preflight Tests`, `Evaluation GitHub Tests`, `Evaluation Command Execution`, `Health Check API`, `Golden Agent Tests`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Why does `ResolvedQuery` connect `Query and Session Context` to `Research Agent State Flow`, `Calculation and Retrieval Branches`, `Research Planning Runtime`, `Research Plan Constraints`, `Reconciliation Outcome Tests`, `Operation Reconciliation Flow`, `Model Provider Contracts`, `Research Workflow Readiness`, `Adaptive Retrieval Service`, `Follow Up Plan Replay`, `Company Entity Resolution`, `On Demand Data Preparation`, `Evidence Scope Planning`, `Retrieval Planning and Resolution`, `SQL Research Tools`, `Evaluation Orchestrator`, `Persistence Agent Tests`, `Question Parsing Workflow`, `Case Observation Mapping`, `Session Manager Tests`, `Golden Agent Tests`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `AgentState` connect `Research Agent State Flow` to `Calculation and Retrieval Branches`, `Query and Session Context`, `Financial Calculation Engine`, `Citation Repair Workflow`, `Operation Reconciliation Flow`, `Model Provider Contracts`, `Persistent Research Agent`, `Follow Up Plan Replay`, `Answer Display Formatting`, `Question Parsing Workflow`, `Case Observation Mapping`, `Research Session Output`, `Research Worker Service`, `Golden Agent Runner`, `Session Manager Tests`, `Agent CLI Tests`, `Research Worker Leasing`, `Fallback Financial Answers`, `Agent Execution Events`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 90 inferred relationships involving `ResolvedQuery` (e.g. with `AgentCapability` and `AgentError`) actually correct?**
  _`ResolvedQuery` has 90 INFERRED edges - model-reasoned connections that need verification._
- **Are the 105 inferred relationships involving `QuestionAnalysis` (e.g. with `CalculationIntent` and `ModelCalculationIntent`) actually correct?**
  _`QuestionAnalysis` has 105 INFERRED edges - model-reasoned connections that need verification._
- **Are the 94 inferred relationships involving `ExecutionPlan` (e.g. with `CalculationIntent` and `ModelCalculationIntent`) actually correct?**
  _`ExecutionPlan` has 94 INFERRED edges - model-reasoned connections that need verification._
- **Are the 92 inferred relationships involving `Settings` (e.g. with `ResearchApplicationConfigurationError` and `OpenAIResearchModelProvider`) actually correct?**
  _`Settings` has 92 INFERRED edges - model-reasoned connections that need verification._