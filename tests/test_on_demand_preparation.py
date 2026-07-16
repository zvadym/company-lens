from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from company_lens.config import Settings
from company_lens.ingestion import on_demand
from company_lens.ingestion.on_demand import OnDemandCompanyDataPreparer
from company_lens.ingestion.preparation_requirements import (
    CompanyDataPreparationRequirements,
    company_data_is_ready,
)


def _preparer() -> OnDemandCompanyDataPreparer:
    return OnDemandCompanyDataPreparer(
        settings=Settings(_env_file=None),
        session_factory=sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:")),
        embedder=None,
        index_name="test-index",
        index_version="v1",
    )


@contextmanager
def _client() -> Any:
    yield object()


def test_readiness_depends_only_on_requested_company_data() -> None:
    facts_only = CompanyDataPreparationRequirements(financial_facts=True)
    documents_only = CompanyDataPreparationRequirements(documents=True)
    combined = CompanyDataPreparationRequirements(financial_facts=True, documents=True)

    assert company_data_is_ready(
        financial_fact_count=1,
        indexed_chunk_count=0,
        requirements=facts_only,
    )
    assert not company_data_is_ready(
        financial_fact_count=0,
        indexed_chunk_count=1,
        requirements=facts_only,
    )
    assert company_data_is_ready(
        financial_fact_count=0,
        indexed_chunk_count=1,
        requirements=documents_only,
    )
    assert not company_data_is_ready(
        financial_fact_count=1,
        indexed_chunk_count=0,
        requirements=combined,
    )


def test_facts_only_preparation_does_not_run_document_pipeline(monkeypatch: Any) -> None:
    preparer = _preparer()
    monkeypatch.setattr(preparer, "_ready_tickers", lambda tickers, requirements: ())
    monkeypatch.setattr(on_demand, "build_company_facts_client", lambda settings: _client())
    monkeypatch.setattr(
        on_demand,
        "build_sec_client_from_settings",
        lambda settings: (_ for _ in ()).throw(AssertionError("SEC ingestion must not run")),
    )

    class FactsService:
        def __init__(self, **_: object) -> None:
            pass

        def ingest(self, _: object) -> SimpleNamespace:
            return SimpleNamespace(facts_seen=8, failures=0)

    monkeypatch.setattr(on_demand, "CompanyFactsIngestionService", FactsService)
    monkeypatch.setattr(
        on_demand,
        "DocumentProcessingService",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("processing must not run")),
    )
    monkeypatch.setattr(
        on_demand,
        "EmbeddingIndexingService",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("embedding must not run")),
    )

    result = preparer.prepare(
        tickers=("MDB",),
        requirements=CompanyDataPreparationRequirements(financial_facts=True),
    )

    assert result.status == "success"
    assert result.facts_seen == 8
    assert result.filings_seen == 0
    assert result.documents_processed == 0
    assert result.chunks_indexed == 0


def test_documents_only_preparation_does_not_run_company_facts(monkeypatch: Any) -> None:
    preparer = _preparer()
    document_id = uuid.uuid4()
    monkeypatch.setattr(preparer, "_ready_tickers", lambda tickers, requirements: ())
    monkeypatch.setattr(preparer, "_document_version_ids", lambda tickers: (document_id,))
    monkeypatch.setattr(on_demand, "build_sec_client_from_settings", lambda settings: _client())
    monkeypatch.setattr(
        on_demand,
        "build_company_facts_client",
        lambda settings: (_ for _ in ()).throw(AssertionError("facts ingestion must not run")),
    )

    class SecService:
        def __init__(self, **_: object) -> None:
            pass

        def ingest(self, _: object) -> SimpleNamespace:
            return SimpleNamespace(companies_seen=1, filings_seen=2, failures=0)

    class ProcessingService:
        def __init__(self, **_: object) -> None:
            pass

        def process(self, _: object) -> SimpleNamespace:
            return SimpleNamespace(documents_processed=2)

    class IndexingService:
        def __init__(self, **_: object) -> None:
            pass

        def index_chunks(self, _: object) -> SimpleNamespace:
            return SimpleNamespace(indexed=5, failed=0)

    monkeypatch.setattr(on_demand, "SecIngestionService", SecService)
    monkeypatch.setattr(on_demand, "DocumentProcessingService", ProcessingService)
    monkeypatch.setattr(on_demand, "EmbeddingIndexingService", IndexingService)

    result = preparer.prepare(
        tickers=("MDB",),
        requirements=CompanyDataPreparationRequirements(documents=True),
    )

    assert result.status == "success"
    assert result.facts_seen == 0
    assert result.filings_seen == 2
    assert result.documents_processed == 2
    assert result.chunks_indexed == 5


def test_combined_preparation_runs_sec_and_company_facts_ingestion(monkeypatch: Any) -> None:
    preparer = _preparer()
    calls: list[str] = []
    monkeypatch.setattr(preparer, "_ready_tickers", lambda tickers, requirements: ())
    monkeypatch.setattr(preparer, "_document_version_ids", lambda tickers: ())
    monkeypatch.setattr(on_demand, "build_sec_client_from_settings", lambda settings: _client())
    monkeypatch.setattr(on_demand, "build_company_facts_client", lambda settings: _client())

    class SecService:
        def __init__(self, **_: object) -> None:
            pass

        def ingest(self, _: object) -> SimpleNamespace:
            calls.append("documents")
            return SimpleNamespace(companies_seen=1, filings_seen=1, failures=0)

    class FactsService:
        def __init__(self, **_: object) -> None:
            pass

        def ingest(self, _: object) -> SimpleNamespace:
            calls.append("financial_facts")
            return SimpleNamespace(facts_seen=8, failures=0)

    monkeypatch.setattr(on_demand, "SecIngestionService", SecService)
    monkeypatch.setattr(on_demand, "CompanyFactsIngestionService", FactsService)

    result = preparer.prepare(
        tickers=("MDB",),
        requirements=CompanyDataPreparationRequirements(
            financial_facts=True,
            documents=True,
        ),
    )

    assert result.status == "success"
    assert calls == ["documents", "financial_facts"]
