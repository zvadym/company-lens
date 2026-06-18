from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.config import get_settings
from company_lens.db.models import CompanyTicker, DocumentKind, IngestionFailure
from company_lens.db.session import build_session_factory
from company_lens.ingestion.artifacts import ArtifactStore
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
from company_lens.processing.service import (
    DEFAULT_CHUNKING_VERSION,
    DEFAULT_SUMMARY_PROMPT_VERSION,
    DocumentProcessingOptions,
    DocumentProcessingService,
)
from company_lens.processing.stats import corpus_stats, demo_chunks
from company_lens.retrieval.benchmark import (
    print_benchmark_report,
    run_benchmark,
    write_json_report,
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
        default="local-feature-hashing.v1",
        help="Embedding index version.",
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
        default="local-feature-hashing.v1",
        help="Embedding index version.",
    )
    retrieve_parser.add_argument("--company-id", action="append", default=None)
    retrieve_parser.add_argument("--document-version-id", action="append", default=None)
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

    args = parser.parse_args(argv)
    if args.command == "ingest-sec":
        return _run_ingest_sec(args)
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
    if args.command == "benchmark-retrieval":
        return _run_benchmark_retrieval(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


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
    session_factory = build_session_factory(settings.database_url)
    request = EmbeddingIndexingRequest(
        index_name=args.index_name,
        index_version=args.index_version,
        limit=args.limit,
        batch_size=args.batch_size,
        force=bool(args.force),
    )
    with session_factory() as session:
        result = EmbeddingIndexingService(session=session).index_chunks(request)
    print(result.model_dump_json(indent=2))
    return 0 if result.failed == 0 else 1


def _run_retrieve(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        filters = RetrievalFilters(
            company_ids=_uuid_tuple(args.company_id or ()),
            document_version_ids=_uuid_tuple(args.document_version_id or ()),
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
        response = RetrievalService(session=session).retrieve(request)
    print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


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
