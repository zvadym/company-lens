from __future__ import annotations

import uuid
from collections.abc import Iterator

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
