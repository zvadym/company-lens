from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from company_lens.api.app import create_app
from company_lens.api.dependencies import get_api_settings
from company_lens.config import Settings
from company_lens.db.models import (
    Company,
    CompanyTicker,
    Exchange,
    RateLimitBucket,
    ResearchEvent,
    ResearchFeedback,
    ResearchRun,
)
from company_lens.research.repository import ResearchRunRepository

TABLES = (
    Company.__table__,
    Exchange.__table__,
    CompanyTicker.__table__,
    ResearchRun.__table__,
    ResearchEvent.__table__,
    ResearchFeedback.__table__,
    RateLimitBucket.__table__,
)


@pytest.fixture
def api() -> Iterator[tuple[TestClient, ResearchRunRepository, sessionmaker]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in TABLES:
        cast_table = table
        cast_table.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = ResearchRunRepository(factory)
    app = create_app(research_repository=repository)
    app.dependency_overrides[get_api_settings] = lambda: Settings(
        database_url="sqlite+pysqlite:///:memory:",
        research_sse_poll_seconds=0.001,
        research_sse_heartbeat_seconds=0.01,
        research_start_rate_limit_per_minute=10,
        feedback_rate_limit_per_minute=10,
        _env_file=None,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, repository, factory
    for table in reversed(TABLES):
        cast_table = table
        cast_table.drop(engine, checkfirst=True)
    engine.dispose()


def test_start_get_cancel_and_reconnect_event_stream(api) -> None:
    client, _, _ = api
    started = client.post("/api/v1/research", json={"question": "Compare NET revenue"})

    assert started.status_code == 202
    accepted = started.json()
    run_id = accepted["run_id"]
    assert accepted["status"] == "queued"
    assert accepted["events_url"].endswith(f"/api/v1/research/{run_id}/events")

    queued = client.get(f"/api/v1/research/{run_id}")
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"

    cancelled = client.delete(f"/api/v1/research/{run_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.delete(f"/api/v1/research/{run_id}").json()["status"] == "cancelled"

    stream = client.get(f"/api/v1/research/{run_id}/events")
    assert stream.status_code == 200
    assert "event: run.status" in stream.text
    assert "event: run.terminal" in stream.text
    event_ids = [
        int(line.removeprefix("id: "))
        for line in stream.text.splitlines()
        if line.startswith("id: ")
    ]
    resumed = client.get(
        f"/api/v1/research/{run_id}/events",
        headers={"Last-Event-ID": str(event_ids[0])},
    )
    assert f"id: {event_ids[0]}\n" not in resumed.text
    assert f"id: {event_ids[-1]}\n" in resumed.text

    query_resumed = client.get(
        f"/api/v1/research/{run_id}/events?after_id={event_ids[-1]}",
        headers={"Last-Event-ID": str(event_ids[0])},
    )
    assert not any(line.startswith("id: ") for line in query_resumed.text.splitlines())


def test_session_conflict_and_public_errors_are_typed(api) -> None:
    client, _, _ = api
    payload = {"question": "Revenue?", "session_id": "same-session"}
    assert client.post("/api/v1/research", json=payload).status_code == 202

    conflict = client.post("/api/v1/research", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "research_session_busy"

    missing = client.get(f"/api/v1/research/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "research_run_not_found",
        "message": "Research run was not found.",
        "correlation_id": missing.headers["X-Request-ID"],
    }

    invalid = client.post("/api/v1/research", json={"question": " "})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "request_validation_failed"
    assert "errors" not in invalid.json()


def test_feedback_companies_sources_and_openapi(api) -> None:
    client, _, factory = api
    company_id = uuid.uuid4()
    exchange_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            Exchange(id=exchange_id, mic="XNYS", code="NYSE", name="New York Stock Exchange")
        )
        session.add(
            Company(
                id=company_id,
                legal_name="Cloudflare, Inc.",
                display_name="Cloudflare",
                cik="1477333",
            )
        )
        session.add(
            CompanyTicker(
                company_id=company_id,
                exchange_id=exchange_id,
                symbol="NET",
                is_primary=True,
            )
        )

    started = client.post("/api/v1/research", json={"question": "Revenue?"}).json()
    run_id = started["run_id"]
    feedback = client.post(
        "/api/v1/feedback",
        json={"run_id": run_id, "rating": "positive", "actor_id": "demo-user"},
    )
    assert feedback.status_code == 201
    assert feedback.json()["rating"] == "positive"

    companies = client.get("/api/v1/companies").json()
    assert companies["total"] == 1
    assert companies["items"][0]["primary_ticker"] == "NET"
    assert client.get(f"/api/v1/research/{run_id}/sources").json()["sources"] == []

    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/research" in paths
    assert "/api/v1/research/{run_id}/events" in paths
    assert "/api/v1/feedback" in paths


def test_session_run_history_returns_latest_runs_in_chronological_order(api) -> None:
    client, _, _ = api
    run_ids: list[str] = []
    for question in ("First", "Second", "Third"):
        started = client.post(
            "/api/v1/research",
            json={"question": question, "session_id": "history-session"},
        ).json()
        run_ids.append(started["run_id"])
        client.delete(f"/api/v1/research/{started['run_id']}")

    history = client.get(
        "/api/v1/research",
        params={"session_id": "history-session", "limit": 2},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 3
    assert [item["run_id"] for item in history.json()["items"]] == run_ids[-2:]
    assert client.get("/api/v1/research", params={"session_id": "unknown-session"}).json() == {
        "items": [],
        "total": 0,
    }


def test_event_stream_replays_legacy_v1_rows(api) -> None:
    client, _, factory = api
    started = client.post("/api/v1/research", json={"question": "Legacy"}).json()
    run_id = uuid.UUID(started["run_id"])
    client.delete(f"/api/v1/research/{run_id}")
    with factory.begin() as session:
        session.add(
            ResearchEvent(
                run_id=run_id,
                event_key="legacy:test",
                event_type="retrieval.summary",
                schema_version="1",
                payload_json={"branch_id": "documents", "passages": 2},
                created_at=datetime.now(UTC),
            )
        )

    stream = client.get(f"/api/v1/research/{run_id}/events")
    assert '"schema_version":"1"' in stream.text
    assert '"type":"retrieval.summary"' in stream.text


def test_version_two_event_keys_are_idempotent(api) -> None:
    client, repository, _ = api
    started = client.post("/api/v1/research", json={"question": "Idempotency"}).json()
    run_id = uuid.UUID(started["run_id"])
    payload = {
        "step_id": "step-1",
        "node": "parse_question",
        "branch_id": None,
        "status": "completed",
        "attempt": 1,
        "summary": "Question classified.",
        "duration_ms": 3,
    }
    repository.append_event(run_id, "node.status", payload, event_key="node:stable")
    repository.append_event(run_id, "node.status", payload, event_key="node:stable")

    events = repository.events_after(run_id, 0)
    assert sum(event.type == "node.status" for event in events) == 1


def test_rate_limit_and_input_size_limit(api) -> None:
    client, _, _ = api
    app = client.app
    app.dependency_overrides[get_api_settings] = lambda: Settings(
        research_start_rate_limit_per_minute=1,
        feedback_rate_limit_per_minute=10,
        research_sse_poll_seconds=0.001,
        _env_file=None,
    )
    assert client.post("/api/v1/research", json={"question": "One"}).status_code == 202
    limited = client.post("/api/v1/research", json={"question": "Two"})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    oversized = client.post(
        "/api/v1/research",
        content=b"x" * 20_000,
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"
