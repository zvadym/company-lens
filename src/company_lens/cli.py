from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.config import get_settings
from company_lens.db.models import CompanyTicker, IngestionFailure
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

    args = parser.parse_args(argv)
    if args.command == "ingest-sec":
        return _run_ingest_sec(args)
    if args.command == "ingest-pdfs":
        return _run_ingest_pdfs(args)
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


if __name__ == "__main__":
    raise SystemExit(main())
