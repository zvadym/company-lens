from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.agent.application import (
    ResearchApplicationConfigurationError,
    open_persistent_research_agent,
    open_research_session_manager,
    setup_research_persistence,
)
from company_lens.agent.output import (
    ResearchErrorDetail,
    ResearchErrorOutput,
    ResearchOperationOutput,
    research_run_output,
    research_session_output,
)
from company_lens.agent.persistence import ResearchSessionError, SessionErrorCode
from company_lens.agent.schemas import AgentRunStatus, ExecutionPolicy
from company_lens.config import Settings, get_settings
from company_lens.db.models import CompanyTicker, DocumentKind, IngestionFailure
from company_lens.db.session import build_session_factory
from company_lens.evals.agent_runner import run_golden_agent_dataset
from company_lens.evals.deterministic import (
    evaluate_golden_results,
    format_markdown_report,
    load_regression_gate,
)
from company_lens.evals.golden import (
    golden_dataset_summary,
    load_golden_dataset,
    validate_golden_dataset,
)
from company_lens.financials.schemas import FinancialFactQuery
from company_lens.financials.service import FinancialFactQueryService
from company_lens.ingestion.artifacts import ArtifactStore
from company_lens.ingestion.company_facts import (
    CompanyFactsIngestionService,
    build_company_facts_client,
    build_company_facts_options,
)
from company_lens.ingestion.pdf_manifest import load_investor_pdf_manifest
from company_lens.ingestion.pdf_service import (
    InvestorPdfClientError,
    InvestorPdfIngestionOptions,
    InvestorPdfIngestionService,
    build_investor_pdf_client_from_settings,
)
from company_lens.ingestion.sec_client import SecClientError
from company_lens.ingestion.sec_service import (
    DEFAULT_FORMS,
    SecIngestionService,
    build_default_options,
    build_sec_client_from_settings,
)
from company_lens.macro.client import FredClient, FredClientError
from company_lens.macro.schemas import FredSeriesQuery
from company_lens.macro.service import FredIngestionService, FredQueryService
from company_lens.observability.logging import configure_logging
from company_lens.observability.telemetry import configure_telemetry, shutdown_telemetry
from company_lens.processing.service import (
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_SUMMARY_PROMPT_VERSION,
    DocumentProcessingOptions,
    DocumentProcessingService,
)
from company_lens.processing.stats import corpus_stats, demo_chunks
from company_lens.research.repository import ResearchRunRepository
from company_lens.research.worker import ResearchWorker
from company_lens.retrieval.adaptive import AdaptiveRetrievalService
from company_lens.retrieval.adaptive_schemas import AdaptiveRetrievalRequest
from company_lens.retrieval.benchmark import (
    print_benchmark_report,
    run_benchmark,
    write_json_report,
)
from company_lens.retrieval.embeddings import (
    DEFAULT_OPENAI_INDEX_VERSION,
    Embedder,
    EmbeddingProvider,
    build_embedder,
)
from company_lens.retrieval.indexing import EmbeddingIndexingService
from company_lens.retrieval.schemas import (
    EmbeddingIndexingRequest,
    RetrievalFilters,
    RetrievalRequest,
)
from company_lens.retrieval.service import RetrievalService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="company-lens")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest-sec", help="Ingest SEC filings.")
    ingest_parser.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        help="Ticker to ingest.",
    )
    ingest_parser.add_argument("--all", action="store_true", help="Ingest the configured universe.")
    ingest_parser.add_argument(
        "--form",
        action="append",
        dest="forms",
        choices=DEFAULT_FORMS,
        default=None,
        help="SEC form type to ingest. Can be repeated.",
    )
    ingest_parser.add_argument(
        "--include-exhibits",
        action="store_true",
        help="Download filing exhibit documents from the SEC archive index.",
    )
    ingest_parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry companies with unresolved prior ingestion failures.",
    )

    facts_parser = subparsers.add_parser(
        "ingest-company-facts",
        help="Ingest canonical financial metrics from SEC Company Facts.",
    )
    facts_parser.add_argument("--ticker", action="append", dest="tickers")
    facts_parser.add_argument("--all", action="store_true", help="Ingest the configured universe.")
    facts_parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("config/financial_metric_mappings.v1.yaml"),
        help="Versioned canonical metric mapping YAML.",
    )

    facts_query_parser = subparsers.add_parser(
        "query-financial-facts",
        help="Query typed canonical financial observations.",
    )
    facts_query_parser.add_argument("--ticker", action="append", dest="tickers", default=None)
    facts_query_parser.add_argument("--metric", action="append", dest="metrics", required=True)
    facts_query_parser.add_argument("--fiscal-year", action="append", type=int, default=None)
    facts_query_parser.add_argument("--fiscal-period", action="append", default=None)
    facts_query_parser.add_argument(
        "--period-type",
        action="append",
        choices=["instant", "quarter", "year_to_date", "annual", "other"],
        default=None,
    )
    facts_query_parser.add_argument("--unit", action="append", dest="units", default=None)
    facts_query_parser.add_argument("--period-start", default=None)
    facts_query_parser.add_argument("--period-end", default=None)
    facts_query_parser.add_argument("--exclude-amendments", action="store_true")
    facts_query_parser.add_argument("--limit", type=int, default=200)

    fred_ingest_parser = subparsers.add_parser(
        "ingest-fred",
        help="Fetch and cache revision-aware FRED observations.",
    )
    fred_ingest_parser.add_argument("--series", action="append", dest="series_ids", required=True)
    fred_ingest_parser.add_argument("--observation-start", default=None)
    fred_ingest_parser.add_argument("--observation-end", default=None)

    fred_query_parser = subparsers.add_parser(
        "query-fred",
        help="Query cached typed FRED observations.",
    )
    fred_query_parser.add_argument("--series", action="append", dest="series_ids", required=True)
    fred_query_parser.add_argument("--observation-start", default=None)
    fred_query_parser.add_argument("--observation-end", default=None)
    fred_query_parser.add_argument("--include-missing", action="store_true")
    fred_query_parser.add_argument("--limit", type=int, default=1000)

    pdf_parser = subparsers.add_parser("ingest-pdfs", help="Ingest investor-relations PDFs.")
    pdf_parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to a reviewed investor PDF manifest.",
    )

    process_parser = subparsers.add_parser(
        "process-documents",
        help="Create summaries and retrieval chunks from ingested documents.",
    )
    process_parser.add_argument(
        "--document-version-id",
        action="append",
        dest="document_version_ids",
        default=None,
        help="Specific document version UUID to process. Can be repeated.",
    )
    process_parser.add_argument(
        "--kind",
        action="append",
        choices=[DocumentKind.SEC_FILING.value, DocumentKind.INVESTOR_PDF.value],
        default=None,
        help="Document kind to process. Defaults to SEC filings and investor PDFs.",
    )
    process_parser.add_argument("--limit", type=int, default=None, help="Maximum documents.")
    process_parser.add_argument(
        "--strategy",
        choices=["fixed-token", "semantic"],
        default="fixed-token",
        help="Chunking strategy.",
    )
    process_parser.add_argument("--max-tokens", type=int, default=320, help="Chunk token target.")
    process_parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=40,
        help="Token overlap for adjacent chunks.",
    )
    process_parser.add_argument(
        "--chunking-version",
        default=DEFAULT_CHUNKING_VERSION,
        help="Version label stored on chunks.",
    )
    process_parser.add_argument(
        "--summary-prompt-version",
        default=DEFAULT_SUMMARY_PROMPT_VERSION,
        help="Version label stored on summaries.",
    )
    process_parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild outputs even if this processing version already ran.",
    )

    stats_parser = subparsers.add_parser("corpus-stats", help="Print corpus statistics.")
    stats_parser.add_argument(
        "--demo-chunks",
        type=int,
        default=0,
        help="Include this many representative chunks.",
    )

    index_parser = subparsers.add_parser(
        "index-embeddings",
        help="Generate deterministic local embeddings for document chunks.",
    )
    index_parser.add_argument("--index-name", default="default", help="Embedding index name.")
    index_parser.add_argument(
        "--index-version",
        default=DEFAULT_OPENAI_INDEX_VERSION,
        help="Embedding index version.",
    )
    index_parser.add_argument(
        "--embedding-provider",
        choices=["openai", "local"],
        default="openai",
        help="Embedding provider. OpenAI is the production default; local is deterministic.",
    )
    index_parser.add_argument("--limit", type=int, default=None, help="Maximum chunks to index.")
    index_parser.add_argument("--batch-size", type=int, default=100, help="Commit batch size.")
    index_parser.add_argument("--force", action="store_true", help="Rebuild existing embeddings.")

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Run dense, lexical, or hybrid retrieval over document chunks.",
    )
    retrieve_parser.add_argument("--query", required=True, help="Search query.")
    retrieve_parser.add_argument(
        "--mode",
        choices=["dense", "lexical", "hybrid"],
        default="hybrid",
        help="Retrieval mode.",
    )
    retrieve_parser.add_argument("--top-k", type=int, default=10, help="Number of results.")
    retrieve_parser.add_argument("--index-name", default="default", help="Embedding index name.")
    retrieve_parser.add_argument(
        "--index-version",
        default=DEFAULT_OPENAI_INDEX_VERSION,
        help="Embedding index version.",
    )
    retrieve_parser.add_argument(
        "--embedding-provider",
        choices=["openai", "local"],
        default="openai",
        help="Provider used to embed the query; it must match the selected index.",
    )
    retrieve_parser.add_argument("--company-id", action="append", default=None)
    retrieve_parser.add_argument("--document-version-id", action="append", default=None)
    retrieve_parser.add_argument("--accession-number", action="append", default=None)
    retrieve_parser.add_argument(
        "--kind",
        action="append",
        choices=[DocumentKind.SEC_FILING.value, DocumentKind.INVESTOR_PDF.value],
        default=None,
    )
    retrieve_parser.add_argument("--filing-form", action="append", default=None)
    retrieve_parser.add_argument("--filing-date-from", default=None)
    retrieve_parser.add_argument("--filing-date-to", default=None)
    retrieve_parser.add_argument("--period-end-from", default=None)
    retrieve_parser.add_argument("--period-end-to", default=None)
    retrieve_parser.add_argument("--fiscal-year", action="append", type=int, default=None)
    retrieve_parser.add_argument("--fiscal-period", action="append", default=None)
    retrieve_parser.add_argument("--section-code", action="append", default=None)
    retrieve_parser.add_argument("--source-system", action="append", default=None)
    retrieve_parser.add_argument("--include-parent-text", action="store_true")

    adaptive_parser = subparsers.add_parser(
        "adaptive-retrieve",
        help="Resolve exact entities and build a budgeted evidence context.",
    )
    adaptive_parser.add_argument("--query", required=True, help="Natural-language question.")
    adaptive_parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum bounded retrieval attempts.",
    )
    adaptive_parser.add_argument("--index-name", default="default")
    adaptive_parser.add_argument("--index-version", default=DEFAULT_OPENAI_INDEX_VERSION)
    adaptive_parser.add_argument(
        "--embedding-provider",
        choices=["openai", "local"],
        default="openai",
        help="Provider used for dense retrieval queries.",
    )

    benchmark_parser = subparsers.add_parser(
        "benchmark-retrieval",
        help="Compare dense, lexical, and hybrid retrieval on a labelled dataset.",
    )
    benchmark_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/retrieval/golden/synthetic.yaml"),
        help="Path to benchmark YAML dataset.",
    )
    benchmark_parser.add_argument("--output-json", type=Path, default=None)

    # Keep validation available without requiring an evaluator runtime or database connection.
    golden_parser = subparsers.add_parser(
        "validate-golden-dataset",
        help="Validate a framework-neutral golden evaluation dataset.",
    )
    golden_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/golden/follow_up.v1.yaml"),
        help="Path to golden dataset YAML.",
    )
    golden_parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")

    eval_parser = subparsers.add_parser(
        "evaluate-golden-results",
        help="Score observed golden-case results with deterministic checks.",
    )
    eval_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/golden/follow_up.v1.yaml"),
        help="Path to golden dataset YAML.",
    )
    eval_parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="Path to observed golden results JSON.",
    )
    eval_parser.add_argument(
        "--gate",
        type=Path,
        default=None,
        help="Optional versioned regression gate YAML.",
    )
    eval_parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Optional path for a human-readable Markdown report.",
    )
    eval_parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")

    run_eval_parser = subparsers.add_parser(
        "run-golden-agent",
        help="Run the live research agent against golden cases and write observed results JSON.",
    )
    run_eval_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/golden/core.v1.yaml"),
        help="Path to golden dataset YAML.",
    )
    run_eval_parser.add_argument(
        "--output",
        type=Path,
        default=Path("observed-results.json"),
        help="Path for observed results JSON.",
    )
    run_eval_parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        default=None,
        help="Specific golden case id to run. Can be repeated.",
    )
    run_eval_parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Maximum number of selected cases to run.",
    )
    run_eval_parser.add_argument(
        "--session-prefix",
        default="golden-eval",
        help="Prefix for persisted research sessions created by the runner.",
    )
    run_eval_parser.add_argument("--max-tool-calls", type=int, default=10)
    run_eval_parser.add_argument("--max-retries-per-node", type=int, default=2)
    run_eval_parser.add_argument("--max-repair-attempts", type=int, default=1)
    run_eval_parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")

    research_parser = subparsers.add_parser(
        "research",
        help="Run and manage persistent LangGraph research sessions.",
    )
    research_subparsers = research_parser.add_subparsers(
        dest="research_command",
        required=True,
    )
    research_setup_parser = research_subparsers.add_parser(
        "setup",
        help="Initialize LangGraph checkpoint tables.",
    )
    _add_json_options(research_setup_parser)

    research_run_parser = research_subparsers.add_parser(
        "run",
        help="Run a new research turn.",
    )
    research_run_parser.add_argument("question", help="Natural-language research question.")
    research_run_parser.add_argument(
        "--session-id",
        default=None,
        help="Session identifier. A UUID is generated when omitted.",
    )
    research_run_parser.add_argument("--max-tool-calls", type=int, default=10)
    research_run_parser.add_argument("--max-retries-per-node", type=int, default=2)
    research_run_parser.add_argument("--max-repair-attempts", type=int, default=1)
    _add_research_output_options(research_run_parser)

    research_resume_parser = research_subparsers.add_parser(
        "resume",
        help="Resume an unfinished research run.",
    )
    research_resume_parser.add_argument("session_id")
    _add_research_output_options(research_resume_parser)

    research_inspect_parser = research_subparsers.add_parser(
        "inspect",
        help="Inspect the latest safe session state.",
    )
    research_inspect_parser.add_argument("session_id")
    _add_research_output_options(research_inspect_parser)

    research_clear_parser = research_subparsers.add_parser(
        "clear",
        help="Hard-delete a research session and its checkpoints.",
    )
    research_clear_parser.add_argument("session_id")
    research_clear_parser.add_argument(
        "--yes",
        action="store_true",
        required=True,
        help="Confirm destructive deletion.",
    )
    _add_json_options(research_clear_parser)

    research_expire_parser = research_subparsers.add_parser(
        "expire",
        help="Delete expired inactive research sessions.",
    )
    research_expire_parser.add_argument("--limit", type=int, default=100)
    _add_json_options(research_expire_parser)

    worker_parser = subparsers.add_parser(
        "research-worker",
        help="Execute durable research runs from the PostgreSQL queue.",
    )
    worker_parser.add_argument("--once", action="store_true", help="Claim at most one run.")

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_telemetry(settings)
    try:
        return _dispatch_command(args)
    finally:
        shutdown_telemetry()


def _dispatch_command(args: argparse.Namespace) -> int:
    if args.command == "ingest-sec":
        return _run_ingest_sec(args)
    if args.command == "ingest-company-facts":
        return _run_ingest_company_facts(args)
    if args.command == "query-financial-facts":
        return _run_query_financial_facts(args)
    if args.command == "ingest-fred":
        return _run_ingest_fred(args)
    if args.command == "query-fred":
        return _run_query_fred(args)
    if args.command == "ingest-pdfs":
        return _run_ingest_pdfs(args)
    if args.command == "process-documents":
        return _run_process_documents(args)
    if args.command == "corpus-stats":
        return _run_corpus_stats(args)
    if args.command == "index-embeddings":
        return _run_index_embeddings(args)
    if args.command == "retrieve":
        return _run_retrieve(args)
    if args.command == "adaptive-retrieve":
        return _run_adaptive_retrieve(args)
    if args.command == "benchmark-retrieval":
        return _run_benchmark_retrieval(args)
    if args.command == "validate-golden-dataset":
        return _run_validate_golden_dataset(args)
    if args.command == "evaluate-golden-results":
        return _run_evaluate_golden_results(args)
    if args.command == "run-golden-agent":
        return _run_golden_agent(args)
    if args.command == "research":
        return _run_research(args)
    if args.command == "research-worker":
        return _run_research_worker(args)
    raise AssertionError(f"Unknown command: {args.command}")


def _add_json_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")


def _run_research_worker(args: argparse.Namespace) -> int:
    settings = get_settings()
    repository = ResearchRunRepository(build_session_factory(settings.database_url))
    try:
        with open_persistent_research_agent(settings) as agent:
            worker = ResearchWorker(
                repository=repository,
                agent=agent,
                lease=timedelta(seconds=settings.research_worker_lease_seconds),
            )
            if args.once:
                worker.run_once()
            else:
                worker.run_forever(poll_seconds=settings.research_worker_poll_seconds)
    except ResearchApplicationConfigurationError as exc:
        print(f"Research worker configuration failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


def _add_research_output_options(parser: argparse.ArgumentParser) -> None:
    _add_json_options(parser)
    parser.add_argument(
        "--include-trajectory",
        action="store_true",
        help="Include the safe node execution timeline.",
    )


def _run_research(args: argparse.Namespace) -> int:
    try:
        settings = get_settings()
        if args.research_command == "setup":
            setup_research_persistence(settings)
            _print_model(ResearchOperationOutput(operation="setup"), pretty=args.pretty)
            return 0
        if args.research_command == "run":
            policy = ExecutionPolicy(
                max_tool_calls=args.max_tool_calls,
                max_retries_per_node=args.max_retries_per_node,
                max_repair_attempts=args.max_repair_attempts,
            )
            session_id = args.session_id or str(uuid.uuid4())
            with open_persistent_research_agent(settings) as agent:
                state = agent.run(args.question, session_id=session_id, policy=policy)
            _print_model(
                research_run_output(state, include_trajectory=args.include_trajectory),
                pretty=args.pretty,
            )
            return 1 if state["status"] is AgentRunStatus.FAILED else 0
        if args.research_command == "resume":
            with open_persistent_research_agent(settings) as agent:
                state = agent.resume(args.session_id)
            _print_model(
                research_run_output(state, include_trajectory=args.include_trajectory),
                pretty=args.pretty,
            )
            return 1 if state["status"] is AgentRunStatus.FAILED else 0
        if args.research_command == "inspect":
            with open_research_session_manager(settings) as manager:
                snapshot = manager.inspect_session(args.session_id)
            if snapshot is None:
                raise ResearchSessionError(
                    SessionErrorCode.NOT_FOUND,
                    "Research session does not exist.",
                )
            _print_model(
                research_session_output(snapshot, include_trajectory=args.include_trajectory),
                pretty=args.pretty,
            )
            return 0
        if args.research_command == "clear":
            with open_research_session_manager(settings) as manager:
                deleted = manager.clear_session(args.session_id)
            _print_model(
                ResearchOperationOutput(
                    operation="clear",
                    session_id=args.session_id,
                    deleted=deleted,
                ),
                pretty=args.pretty,
            )
            return 0
        if args.research_command == "expire":
            with open_research_session_manager(settings) as manager:
                expired = manager.expire_sessions(limit=args.limit)
            _print_model(
                ResearchOperationOutput(operation="expire", expired=expired),
                pretty=args.pretty,
            )
            return 0
        raise ValueError("Unknown research command.")
    except KeyboardInterrupt:
        _print_research_error(
            "interrupted",
            "Research command was interrupted.",
            pretty=args.pretty,
        )
        return 130
    except ResearchSessionError as exc:
        _print_research_error(exc.code.value, str(exc), pretty=args.pretty)
        return 1
    except ResearchApplicationConfigurationError as exc:
        _print_research_error("research_configuration_failed", str(exc), pretty=args.pretty)
        return 1
    except ValueError:
        _print_research_error(
            "invalid_research_request",
            "Research command configuration or input is invalid.",
            pretty=args.pretty,
        )
        return 1
    except Exception:
        _print_research_error(
            "research_operation_failed",
            "Research command failed.",
            pretty=args.pretty,
        )
        return 1


def _print_model(model: BaseModel, *, pretty: bool, stderr: bool = False) -> None:
    print(
        model.model_dump_json(indent=2 if pretty else None),
        file=sys.stderr if stderr else sys.stdout,
    )


def _print_research_error(code: str, message: str, *, pretty: bool) -> None:
    _print_model(
        ResearchErrorOutput(error=ResearchErrorDetail(code=code, message=message)),
        pretty=pretty,
        stderr=True,
    )


def _run_ingest_sec(args: argparse.Namespace) -> int:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        tickers = tuple(args.tickers or ())
        if args.retry_failed:
            failed_tickers = _find_failed_tickers(session)
            tickers = tuple(dict.fromkeys((*tickers, *failed_tickers)))
        options = build_default_options(
            tickers=tickers,
            all_companies=bool(args.all),
            forms=tuple(args.forms or DEFAULT_FORMS),
            settings=settings,
            download_exhibits=bool(args.include_exhibits),
        )
        artifact_store = ArtifactStore(settings.sec_artifact_root)
        try:
            with build_sec_client_from_settings(settings) as client:
                result = SecIngestionService(
                    session=session,
                    client=client,
                    artifact_store=artifact_store,
                ).ingest(options)
        except (ValueError, SecClientError) as exc:
            print(f"SEC ingestion failed: {exc}")
            return 1

    print(
        "SEC ingestion completed: "
        f"run_id={result.run_id} status={result.status} "
        f"companies={result.companies_seen} filings={result.filings_seen} "
        f"artifacts={result.artifacts_seen} failures={result.failures}"
    )
    return 0 if result.status == "success" else 1


def _run_ingest_company_facts(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        options = build_company_facts_options(
            tickers=tuple(args.tickers or ()),
            all_companies=bool(args.all),
            mapping_path=args.mapping,
        )
    except (OSError, ValueError) as exc:
        print(f"SEC Company Facts ingestion failed: {exc}")
        return 1

    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        try:
            with build_company_facts_client(settings) as client:
                result = CompanyFactsIngestionService(
                    session=session,
                    client=client,
                    artifact_store=ArtifactStore(settings.sec_artifact_root),
                ).ingest(options)
        except (OSError, ValueError, SecClientError) as exc:
            print(f"SEC Company Facts ingestion failed: {exc}")
            return 1
    print(
        "SEC Company Facts ingestion completed: "
        f"run_id={result.run_id} status={result.status} "
        f"companies={result.companies_seen} facts_seen={result.facts_seen} "
        f"inserted={result.facts_inserted} duplicates={result.duplicates_skipped} "
        f"unmapped_concepts={result.unmapped_concepts} failures={result.failures}"
    )
    return 0 if result.status == "success" else 1


def _run_query_financial_facts(args: argparse.Namespace) -> int:
    try:
        request = FinancialFactQuery(
            tickers=tuple(args.tickers or ()),
            metrics=tuple(args.metrics),
            fiscal_years=tuple(args.fiscal_year or ()),
            fiscal_periods=tuple(args.fiscal_period or ()),
            period_types=tuple(args.period_type or ()),
            units=tuple(args.units or ()),
            period_start=_optional_date(args.period_start),
            period_end=_optional_date(args.period_end),
            include_amendments=not bool(args.exclude_amendments),
            limit=args.limit,
        )
    except (TypeError, ValueError) as exc:
        print(f"Financial facts query failed: {exc}")
        return 1
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        result = FinancialFactQueryService(session=session).query(request)
    print(result.model_dump_json(indent=2))
    return 0


def _run_ingest_fred(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.fred_api_key:
        print("FRED ingestion failed: set FRED_API_KEY or COMPANY_LENS_FRED_API_KEY.")
        return 1
    try:
        observation_start = _optional_date(args.observation_start)
        observation_end = _optional_date(args.observation_end)
        session_factory = build_session_factory(settings.database_url)
        with (
            session_factory() as session,
            FredClient(
                api_key=settings.fred_api_key.get_secret_value(),
                base_url=settings.fred_base_url,
                timeout_seconds=settings.fred_request_timeout_seconds,
                retry_attempts=settings.fred_retry_attempts,
            ) as client,
        ):
            result = FredIngestionService(session=session, client=client).ingest(
                tuple(args.series_ids),
                observation_start=observation_start,
                observation_end=observation_end,
            )
    except (OSError, TypeError, ValueError, FredClientError) as exc:
        print(f"FRED ingestion failed: {exc}")
        return 1
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "success" else 1


def _run_query_fred(args: argparse.Namespace) -> int:
    try:
        request = FredSeriesQuery(
            series_ids=tuple(args.series_ids),
            observation_start=_optional_date(args.observation_start),
            observation_end=_optional_date(args.observation_end),
            include_missing=bool(args.include_missing),
            limit=args.limit,
        )
    except (TypeError, ValueError) as exc:
        print(f"FRED query failed: {exc}")
        return 1
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        result = FredQueryService(session=session).query(request)
    print(result.model_dump_json(indent=2))
    return 0


def _run_ingest_pdfs(args: argparse.Namespace) -> int:
    settings = get_settings()
    manifest_path = args.manifest or settings.investor_pdf_manifest_path
    try:
        documents = load_investor_pdf_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        print(f"Investor PDF ingestion failed: {exc}")
        return 1

    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        artifact_store = ArtifactStore(settings.investor_pdf_artifact_root)
        try:
            with build_investor_pdf_client_from_settings(settings) as client:
                result = InvestorPdfIngestionService(
                    session=session,
                    client=client,
                    artifact_store=artifact_store,
                ).ingest(InvestorPdfIngestionOptions(documents=documents))
        except InvestorPdfClientError as exc:
            print(f"Investor PDF ingestion failed: {exc}")
            return 1

    print(
        "Investor PDF ingestion completed: "
        f"run_id={result.run_id} status={result.status} "
        f"documents={result.documents_seen} pages={result.pages_seen} "
        f"blocks={result.blocks_seen} artifacts={result.artifacts_seen} "
        f"failures={result.failures}"
    )
    return 0 if result.status == "success" else 1


def _run_process_documents(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        document_version_ids = tuple(
            uuid.UUID(value) for value in (args.document_version_ids or ())
        )
    except ValueError as exc:
        print(f"Document processing failed: invalid document version UUID: {exc}")
        return 1

    kinds = (
        tuple(DocumentKind(value) for value in args.kind)
        if args.kind
        else (DocumentKind.SEC_FILING, DocumentKind.INVESTOR_PDF)
    )
    options = DocumentProcessingOptions(
        document_version_ids=document_version_ids,
        document_kinds=kinds,
        limit=args.limit,
        chunking_strategy=args.strategy,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
        chunking_version=args.chunking_version,
        summary_prompt_version=args.summary_prompt_version,
        force=bool(args.force),
    )

    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        try:
            result = DocumentProcessingService(session=session).process(options)
        except (OSError, ValueError) as exc:
            print(f"Document processing failed: {exc}")
            return 1

    print(
        "Document processing completed: "
        f"status={result.status} documents_seen={result.documents_seen} "
        f"processed={result.documents_processed} skipped={result.documents_skipped} "
        f"sections={result.sections_seen} summaries={result.summaries_written} "
        f"chunks={result.chunks_written} tokens={result.token_count} "
        f"duplicates_removed={result.duplicate_chunks_removed} "
        f"duplicate_rate={result.duplicate_chunk_rate} "
        f"boilerplate_removed={result.boilerplate_chunks_removed} "
        f"boilerplate_rate={result.boilerplate_chunk_rate}"
    )
    return 0


def _run_corpus_stats(args: argparse.Namespace) -> int:
    settings = get_settings()
    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        payload = corpus_stats(session)
        if args.demo_chunks:
            payload["demo_chunks"] = demo_chunks(session, limit=args.demo_chunks)

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_index_embeddings(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        embedder = _build_embedder(args.embedding_provider, settings)
    except ValueError as exc:
        print(f"Embedding configuration failed: {exc}")
        return 1
    session_factory = build_session_factory(settings.database_url)
    request = EmbeddingIndexingRequest(
        index_name=args.index_name,
        index_version=args.index_version,
        limit=args.limit,
        batch_size=args.batch_size,
        force=bool(args.force),
    )
    with session_factory() as session:
        result = EmbeddingIndexingService(session=session, embedder=embedder).index_chunks(request)
    print(result.model_dump_json(indent=2))
    return 0 if result.failed == 0 else 1


def _run_retrieve(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        embedder = _build_embedder(args.embedding_provider, settings)
        filters = RetrievalFilters(
            company_ids=_uuid_tuple(args.company_id or ()),
            document_version_ids=_uuid_tuple(args.document_version_id or ()),
            accession_numbers=tuple(args.accession_number or ()),
            document_kinds=tuple(DocumentKind(value) for value in (args.kind or ())),
            filing_forms=tuple(args.filing_form or ()),
            filing_date_from=_optional_date(args.filing_date_from),
            filing_date_to=_optional_date(args.filing_date_to),
            period_end_from=_optional_date(args.period_end_from),
            period_end_to=_optional_date(args.period_end_to),
            fiscal_years=tuple(args.fiscal_year or ()),
            fiscal_periods=tuple(args.fiscal_period or ()),
            section_codes=tuple(args.section_code or ()),
            source_systems=tuple(args.source_system or ()),
        )
        request = RetrievalRequest(
            query=args.query,
            mode=args.mode,
            top_k=args.top_k,
            index_name=args.index_name,
            index_version=args.index_version,
            filters=filters,
            include_parent_text=bool(args.include_parent_text),
        )
    except (ValueError, TypeError) as exc:
        print(f"Retrieval failed: {exc}")
        return 1

    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        response = RetrievalService(session=session, embedder=embedder).retrieve(request)
    print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _run_adaptive_retrieve(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        embedder = _build_embedder(args.embedding_provider, settings)
        request = AdaptiveRetrievalRequest(
            query=args.query,
            max_attempts=args.max_attempts,
            index_name=args.index_name,
            index_version=args.index_version,
        )
    except (ValueError, TypeError) as exc:
        print(f"Adaptive retrieval failed: {exc}")
        return 1

    session_factory = build_session_factory(settings.database_url)
    with session_factory() as session:
        response = AdaptiveRetrievalService(session=session, embedder=embedder).retrieve(request)
    print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _build_embedder(provider: str, settings: Settings) -> Embedder:
    if provider not in {"local", "openai"}:
        raise ValueError(f"Unsupported embedding provider: {provider}")
    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return build_embedder(
        cast(EmbeddingProvider, provider),
        openai_api_key=api_key,
        openai_model=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
        timeout_seconds=settings.openai_request_timeout_seconds,
        max_retries=settings.openai_retry_attempts,
    )


def _run_benchmark_retrieval(args: argparse.Namespace) -> int:
    try:
        report = run_benchmark(args.dataset)
    except (OSError, ValueError) as exc:
        print(f"Retrieval benchmark failed: {exc}")
        return 1
    print_benchmark_report(report)
    if args.output_json is not None:
        write_json_report(report, args.output_json)
    return 0


def _run_validate_golden_dataset(args: argparse.Namespace) -> int:
    try:
        dataset = validate_golden_dataset(args.dataset)
    except (OSError, ValueError) as exc:
        print(f"Golden dataset validation failed: {exc}")
        return 1
    # Print a small machine-readable summary rather than echoing the full case payload.
    print(json.dumps(golden_dataset_summary(dataset), indent=2 if args.pretty else None))
    return 0


def _run_evaluate_golden_results(args: argparse.Namespace) -> int:
    try:
        gate = load_regression_gate(args.gate) if args.gate is not None else None
        report = evaluate_golden_results(args.dataset, args.results, gate=gate)
        if args.markdown_output is not None:
            args.markdown_output.write_text(
                format_markdown_report(report) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError) as exc:
        print(f"Golden result evaluation failed: {exc}")
        return 1
    print(report.model_dump_json(indent=2 if args.pretty else None))
    return 0 if report.passed else 1


def _run_golden_agent(args: argparse.Namespace) -> int:
    try:
        dataset = load_golden_dataset(args.dataset)
        policy = ExecutionPolicy(
            max_tool_calls=args.max_tool_calls,
            max_retries_per_node=args.max_retries_per_node,
            max_repair_attempts=args.max_repair_attempts,
        )
        with open_persistent_research_agent(get_settings()) as agent:
            observed = run_golden_agent_dataset(
                dataset,
                agent,
                policy=policy,
                max_cases=args.max_cases,
                case_ids=tuple(args.case_ids or ()),
                session_prefix=args.session_prefix,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            observed.model_dump_json(indent=2 if args.pretty else None) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        ValueError,
        ResearchApplicationConfigurationError,
        ResearchSessionError,
    ) as exc:
        print(f"Golden agent run failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "dataset": observed.dataset_name,
                "version": observed.dataset_version,
                "results": len(observed.results),
                "output": str(args.output),
            },
            indent=2 if args.pretty else None,
        )
    )
    return 0


def _find_failed_tickers(session: Session) -> tuple[str, ...]:
    failures = session.scalars(
        select(IngestionFailure).where(IngestionFailure.resolved_at.is_(None))
    ).all()
    tickers: list[str] = []
    for failure in failures:
        ticker = failure.details_json.get("ticker")
        if isinstance(ticker, str):
            tickers.append(ticker.upper())
            continue
        if failure.company_id is None:
            continue
        company_ticker = session.scalar(
            select(CompanyTicker).where(
                CompanyTicker.company_id == failure.company_id,
                CompanyTicker.is_primary.is_(True),
                CompanyTicker.valid_to.is_(None),
            )
        )
        if company_ticker is not None:
            tickers.append(company_ticker.symbol.upper())
    return tuple(dict.fromkeys(tickers))


def _uuid_tuple(values: Sequence[str]) -> tuple[uuid.UUID, ...]:
    return tuple(uuid.UUID(value) for value in values)


def _optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
