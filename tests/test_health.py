from __future__ import annotations

from fastapi.testclient import TestClient

from company_lens.api.app import create_app
from company_lens.db.health import DatabaseHealth


def test_health_returns_ok_when_database_is_reachable(monkeypatch) -> None:
    def fake_check_database(database_url: str) -> DatabaseHealth:
        assert database_url
        return DatabaseHealth(status="ok", latency_ms=1.25)

    monkeypatch.setattr("company_lens.api.v1.health.check_database", fake_check_database)

    client = TestClient(create_app())
    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request"
    assert response.json() == {
        "status": "ok",
        "service": "company-lens-api",
        "version": "0.1.0",
        "environment": "local",
        "correlation_id": "test-request",
        "database": {"status": "ok", "latency_ms": 1.25, "detail": None},
    }


def test_health_returns_503_when_database_is_unreachable(monkeypatch) -> None:
    def fake_check_database(database_url: str) -> DatabaseHealth:
        assert database_url
        return DatabaseHealth(status="error", detail="OperationalError")

    monkeypatch.setattr("company_lens.api.v1.health.check_database", fake_check_database)

    client = TestClient(create_app())
    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == {
        "status": "error",
        "latency_ms": None,
        "detail": "OperationalError",
    }
