from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

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
from company_lens.retrieval.indexing import EmbeddingIndexingService
from company_lens.retrieval.schemas import EmbeddingIndexingRequest, RetrievalMode, RetrievalRequest
from company_lens.retrieval.service import RetrievalService


def run_benchmark(dataset_path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Benchmark dataset must be a mapping.")

    with tempfile.TemporaryDirectory(prefix="company-lens-retrieval-") as tmpdir:
        engine = create_engine(f"sqlite+pysqlite:///{Path(tmpdir) / 'benchmark.db'}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            _seed_dataset(session, payload)
            EmbeddingIndexingService(session=session).index_chunks(EmbeddingIndexingRequest())
            return _evaluate(session, payload)


def print_benchmark_report(report: dict[str, Any]) -> None:
    rows = report["rows"]
    print("mode      queries  recall@k  precision@k  duplicate_rate  latency_ms")
    for row in rows:
        print(
            f"{row['mode']:<9} "
            f"{row['queries']:>7} "
            f"{row['recall_at_k']:>9.3f} "
            f"{row['precision_at_k']:>12.3f} "
            f"{row['duplicate_rate']:>14.3f} "
            f"{row['latency_ms']:>10.1f}"
        )


def write_json_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _seed_dataset(session: Session, payload: dict[str, Any]) -> None:
    company = Company(
        legal_name=payload.get("company", {}).get("legal_name", "Synthetic Company, Inc."),
        display_name=payload.get("company", {}).get("display_name", "Synthetic Company"),
        cik=payload.get("company", {}).get("cik", "0000000000"),
    )
    session.add(company)
    session.flush()

    for document_index, document_payload in enumerate(payload.get("documents", [])):
        document = SourceDocument(
            company_id=company.id,
            kind=DocumentKind(document_payload.get("kind", DocumentKind.SEC_FILING.value)),
            source_system=document_payload.get("source_system", "benchmark"),
            stable_source_id=document_payload["stable_source_id"],
            source_url=document_payload.get("source_url", "https://example.com/benchmark"),
            title=document_payload.get("title"),
            filing_form=document_payload.get("filing_form"),
            fiscal_year=document_payload.get("fiscal_year"),
            fiscal_period=document_payload.get("fiscal_period"),
            metadata_json={},
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_label=document_payload.get("version_label", f"benchmark-{document_index}"),
            content_hash=content_hash(document_payload["stable_source_id"]),
            source_hash=content_hash(document_payload["stable_source_id"]),
            state=DocumentVersionState.CURRENT,
            is_current=True,
            metadata_json={},
        )
        session.add(version)
        session.flush()
        for section_index, section_payload in enumerate(document_payload.get("sections", [])):
            section_text = " ".join(chunk["text"] for chunk in section_payload.get("chunks", []))
            section = FilingSection(
                document_version_id=version.id,
                section_code=section_payload.get("section_code"),
                title=section_payload.get("title", "Section"),
                ordinal_path=section_payload.get("ordinal_path", str(section_index)),
                heading_level=1,
                content_hash=content_hash(section_text),
            )
            session.add(section)
            session.flush()
            for chunk_index, chunk_payload in enumerate(section_payload.get("chunks", [])):
                text = chunk_payload["text"]
                session.add(
                    DocumentChunk(
                        document_version_id=version.id,
                        section_id=section.id,
                        chunk_index=chunk_index,
                        text=text,
                        content_hash=content_hash(text),
                        token_count=len(text.split()),
                        metadata_json={"benchmark_chunk_key": chunk_payload["key"]},
                    )
                )
    session.commit()


def _evaluate(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    modes: tuple[RetrievalMode, ...] = ("dense", "lexical", "hybrid")
    rows: list[dict[str, Any]] = []
    query_payloads = payload.get("queries", [])
    for mode in modes:
        recalls: list[float] = []
        precisions: list[float] = []
        duplicate_rates: list[float] = []
        started = time.perf_counter()
        for query_payload in query_payloads:
            response = RetrievalService(session=session).retrieve(
                RetrievalRequest(
                    query=query_payload["query"],
                    mode=mode,
                    top_k=int(query_payload.get("top_k", 10)),
                )
            )
            expected = set(query_payload.get("expected_chunk_keys", []))
            actual = _result_chunk_keys(session, [result.chunk_id for result in response.results])
            hits = expected & set(actual)
            recalls.append(len(hits) / len(expected) if expected else 1.0)
            precisions.append(len(hits) / len(actual) if actual else 0.0)
            duplicate_rates.append(_duplicate_rate(actual))
        elapsed_ms = (time.perf_counter() - started) * 1000
        rows.append(
            {
                "mode": mode,
                "queries": len(query_payloads),
                "recall_at_k": _average(recalls),
                "precision_at_k": _average(precisions),
                "duplicate_rate": _average(duplicate_rates),
                "latency_ms": elapsed_ms,
            }
        )
    return {"dataset": payload.get("name", "unnamed"), "rows": rows}


def _result_chunk_keys(session: Session, chunk_ids: list[Any]) -> list[str]:
    if not chunk_ids:
        return []
    chunks = session.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))).all()
    by_id = {chunk.id: chunk for chunk in chunks}
    return [
        str(by_id[chunk_id].metadata_json["benchmark_chunk_key"])
        for chunk_id in chunk_ids
        if chunk_id in by_id
    ]


def _duplicate_rate(values: list[str]) -> float:
    if not values:
        return 0.0
    return (len(values) - len(set(values))) / len(values)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
