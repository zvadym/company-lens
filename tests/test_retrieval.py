from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from company_lens import cli
from company_lens.config import Settings
from company_lens.db.base import Base
from company_lens.db.models import (
    Company,
    DocumentChunk,
    DocumentKind,
    DocumentVersion,
    DocumentVersionState,
    FilingSection,
    SourceDocument,
)
from company_lens.processing.text import content_hash
from company_lens.retrieval.benchmark import run_benchmark
from company_lens.retrieval.embeddings import (
    EmbeddingInputTooLongError,
    LocalFeatureHashingEmbedder,
    OpenAIEmbedder,
    build_embedder,
)
from company_lens.retrieval.indexing import EmbeddingIndexingService
from company_lens.retrieval.schemas import (
    EmbeddingIndexingRequest,
    RetrievalFilters,
    RetrievalRequest,
)
from company_lens.retrieval.service import RetrievalService


def test_retrieval_request_rejects_blank_query() -> None:
    with pytest.raises(ValidationError):
        RetrievalRequest(query="   ")


def test_local_feature_hashing_embeddings_are_deterministic() -> None:
    embedder = LocalFeatureHashingEmbedder(dimensions=16)
    first = embedder.embed_text("Revenue growth from enterprise customers")
    second = embedder.embed_text("Revenue growth from enterprise customers")

    assert first == second
    assert len(first) == 16
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_openai_embedder_batches_inputs_and_preserves_response_order() -> None:
    class FakeEmbeddings:
        def create(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs == {
                "model": "text-embedding-3-small",
                "input": ["first", "second"],
                "dimensions": 3,
                "encoding_format": "float",
            }
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[0.0, 1.0, 0.0]),
                    SimpleNamespace(index=0, embedding=[1.0, 0.0, 0.0]),
                ]
            )

    client = SimpleNamespace(embeddings=FakeEmbeddings())
    embedder = OpenAIEmbedder(client=client, dimensions=3)

    assert embedder.embed_texts(["first", "second"]) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]


def test_openai_embedder_rejects_oversized_input_before_api_call() -> None:
    class UnexpectedEmbeddings:
        def create(self, **_kwargs: object) -> None:
            raise AssertionError("OpenAI API must not be called for oversized input")

    embedder = OpenAIEmbedder(
        client=SimpleNamespace(embeddings=UnexpectedEmbeddings()),
        dimensions=3,
    )

    with pytest.raises(EmbeddingInputTooLongError, match="maximum is 8192"):
        embedder.embed_texts(["token " * 9000])


def test_openai_embedder_normalizes_api_key_before_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.embeddings = SimpleNamespace()

    monkeypatch.setattr("company_lens.retrieval.embeddings.OpenAI", FakeOpenAIClient)

    build_embedder("openai", openai_api_key="\n test-key \r")

    assert captured["api_key"] == "test-key"


def test_openai_embedder_rejects_blank_api_key_without_injected_client() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIEmbedder(api_key=" \n\t ")


def test_indexing_isolates_one_invalid_chunk_from_the_batch(session: Session) -> None:
    chunks = _seed_corpus(session)
    chunks[0].text = "reject-me"
    chunks[0].content_hash = content_hash(chunks[0].text)
    session.commit()

    class SelectiveEmbedder:
        model_name = "selective-test-v1"
        dimensions = 384
        provider = "test"

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            if "reject-me" in texts:
                raise ValueError("invalid embedding input")
            return [[1.0] + [0.0] * 383 for _text in texts]

        def embed_query(self, text: str) -> list[float]:
            return self.embed_texts([text])[0]

    result = EmbeddingIndexingService(session=session, embedder=SelectiveEmbedder()).index_chunks(
        EmbeddingIndexingRequest(index_version="selective-test.v1", batch_size=100)
    )

    assert result.indexed == len(chunks) - 1
    assert result.failed == 1
    assert result.failures[0].chunk_id == chunks[0].id
    assert result.failures[0].message == "invalid embedding input"


def test_indexing_skips_fresh_embeddings_and_rebuilds_stale(session: Session) -> None:
    chunks = _seed_corpus(session)
    service = EmbeddingIndexingService(session=session)

    first = service.index_chunks(EmbeddingIndexingRequest(batch_size=2))
    second = service.index_chunks(EmbeddingIndexingRequest(batch_size=2))
    chunks[0].text = "Updated security platform text."
    chunks[0].content_hash = content_hash(chunks[0].text)
    session.commit()
    third = service.index_chunks(EmbeddingIndexingRequest(batch_size=2))

    assert first.indexed == len(chunks)
    assert second.skipped == len(chunks)
    assert third.stale_rebuilt == 1


def test_dense_lexical_and_hybrid_retrieval_with_filters(session: Session) -> None:
    _seed_corpus(session)
    EmbeddingIndexingService(session=session).index_chunks(EmbeddingIndexingRequest())

    lexical = RetrievalService(session=session).retrieve(
        RetrievalRequest(
            query="competition security vendors",
            mode="lexical",
            filters=RetrievalFilters(section_codes=("risk_factors",)),
        )
    )
    dense = RetrievalService(session=session).retrieve(
        RetrievalRequest(query="connectivity cloud platform", mode="dense")
    )
    hybrid = RetrievalService(session=session).retrieve(
        RetrievalRequest(query="enterprise security platform", mode="hybrid")
    )

    assert lexical.results
    assert lexical.results[0].section_code == "risk_factors"
    assert lexical.results[0].scores.lexical_score is not None
    assert dense.results
    assert dense.results[0].scores.vector_score is not None
    assert hybrid.results
    assert hybrid.results[0].scores.hybrid_score is not None
    assert hybrid.results[0].diagnostics.embedding_index_version == "local-feature-hashing.v1"


def test_hybrid_continues_lexical_when_embeddings_are_missing(session: Session) -> None:
    _seed_corpus(session)

    response = RetrievalService(session=session).retrieve(
        RetrievalRequest(query="competition security vendors", mode="hybrid")
    )

    assert response.results
    assert "missing_embedding_index" in response.diagnostics["warnings"]
    assert response.results[0].scores.lexical_score is not None


def test_dedupe_removes_near_identical_results(session: Session) -> None:
    _seed_corpus(session, include_duplicate=True)

    response = RetrievalService(session=session).retrieve(
        RetrievalRequest(
            query="competition security platform vendors",
            mode="lexical",
            top_k=10,
            near_duplicate_threshold=0.8,
        )
    )

    hashes = [result.content_hash for result in response.results]
    assert len(hashes) == len(set(hashes))
    assert response.diagnostics["deduped_candidates"] >= 1


def test_cli_indexes_retrieves_and_runs_benchmark(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _seed_corpus(session)
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    settings = Settings(database_url="sqlite+pysqlite:///unused.db")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_session_factory", lambda _: factory)

    assert (
        cli.main(
            [
                "index-embeddings",
                "--batch-size",
                "2",
                "--embedding-provider",
                "local",
                "--index-version",
                "local-feature-hashing.v1",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            [
                "retrieve",
                "--query",
                "competition security vendors",
                "--mode",
                "hybrid",
                "--embedding-provider",
                "local",
                "--index-version",
                "local-feature-hashing.v1",
            ]
        )
        == 0
    )
    retrieve_output = json.loads(capsys.readouterr().out)
    assert retrieve_output["results"]

    report_path = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "benchmark-retrieval",
                "--dataset",
                "evals/retrieval/golden/synthetic.yaml",
                "--output-json",
                str(report_path),
            ]
        )
        == 0
    )
    assert report_path.exists()


def test_benchmark_runs_all_modes() -> None:
    report = run_benchmark(Path("evals/retrieval/golden/synthetic.yaml"))

    assert {row["mode"] for row in report["rows"]} == {"dense", "lexical", "hybrid"}
    assert all(row["queries"] == 3 for row in report["rows"])


def _seed_corpus(session: Session, *, include_duplicate: bool = False) -> list[DocumentChunk]:
    company = Company(
        legal_name="Cloudflare, Inc.",
        display_name="Cloudflare",
        cik="0001477333",
    )
    session.add(company)
    session.flush()
    document = SourceDocument(
        company_id=company.id,
        kind=DocumentKind.SEC_FILING,
        source_system="sec_edgar",
        stable_source_id="0001477333-26-000001",
        source_url="https://example.com/form10k.htm",
        title="Cloudflare 10-K",
        accession_number="0001477333-26-000001",
        filing_form="10-K",
        fiscal_year=2025,
        fiscal_period="FY",
        metadata_json={},
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_label="0001477333-26-000001",
        content_hash="version-hash",
        source_hash="version-hash",
        state=DocumentVersionState.CURRENT,
        is_current=True,
        metadata_json={},
    )
    session.add(version)
    session.flush()
    business = FilingSection(
        document_version_id=version.id,
        section_code="business",
        title="Business",
        ordinal_path="1",
        heading_level=1,
        content_hash="business-hash",
    )
    risks = FilingSection(
        document_version_id=version.id,
        section_code="risk_factors",
        title="Risk Factors",
        ordinal_path="1A",
        heading_level=1,
        content_hash="risk-hash",
    )
    session.add_all([business, risks])
    session.flush()
    chunk_texts = [
        (
            business,
            "Cloudflare operates a connectivity cloud platform for security and networking.",
        ),
        (
            business,
            "Enterprise customers expanded usage of developer and application services.",
        ),
        (
            risks,
            "Competition from security and cloud platform vendors remains meaningful.",
        ),
        (
            risks,
            "Macroeconomic pressure can reduce customer spending and lengthen sales cycles.",
        ),
    ]
    if include_duplicate:
        chunk_texts.append(
            (
                risks,
                "Competition from security and cloud platform vendors remains meaningful.",
            )
        )
    chunks: list[DocumentChunk] = []
    section_indexes: dict[str, int] = {"business": 0, "risk_factors": 0}
    for section, text in chunk_texts:
        section_key = section.section_code or ""
        chunk = DocumentChunk(
            document_version_id=version.id,
            section_id=section.id,
            chunk_index=section_indexes[section_key],
            text=text,
            content_hash=content_hash(text),
            token_count=len(text.split()),
            metadata_json={},
        )
        section_indexes[section_key] += 1
        session.add(chunk)
        chunks.append(chunk)
    session.commit()
    return chunks


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
