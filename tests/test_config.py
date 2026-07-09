from __future__ import annotations

from pathlib import Path

import yaml

from company_lens.config import Settings


def test_reranker_settings_default_to_noop() -> None:
    settings = Settings()

    assert settings.reranker_provider == "noop"
    assert settings.reranker_url == "http://reranker:8080"
    assert settings.reranker_timeout_seconds == 2.0
    assert settings.reranker_fail_closed is False


def test_reranker_settings_accept_http_provider() -> None:
    settings = Settings(
        reranker_provider="http",
        reranker_url="http://localhost:8080",
        reranker_timeout_seconds=1.5,
        reranker_fail_closed=True,
    )

    assert settings.reranker_provider == "http"
    assert settings.reranker_url == "http://localhost:8080"
    assert settings.reranker_timeout_seconds == 1.5
    assert settings.reranker_fail_closed is True


def test_docker_compose_langfuse_env_prefers_project_key_then_standard_key() -> None:
    for compose_file in ("docker-compose.yml", "docker-compose.dev.yml"):
        compose = yaml.safe_load(Path(compose_file).read_text())
        for service_name in ("api", "worker"):
            environment = compose["services"][service_name]["environment"]
            assert environment["COMPANY_LENS_LANGFUSE_PUBLIC_KEY"] == (
                "${COMPANY_LENS_LANGFUSE_PUBLIC_KEY:-${LANGFUSE_PUBLIC_KEY:-}}"
            )
            assert environment["COMPANY_LENS_LANGFUSE_SECRET_KEY"] == (
                "${COMPANY_LENS_LANGFUSE_SECRET_KEY:-${LANGFUSE_SECRET_KEY:-}}"
            )
            assert environment["COMPANY_LENS_LANGFUSE_BASE_URL"] == (
                "${COMPANY_LENS_LANGFUSE_BASE_URL:-${LANGFUSE_BASE_URL:-https://cloud.langfuse.com}}"
            )


def test_dev_compose_wires_optional_reranker_service() -> None:
    compose = yaml.safe_load(Path("docker-compose.dev.yml").read_text())

    reranker = compose["services"]["reranker"]
    assert reranker["build"]["dockerfile"] == "Dockerfile.reranker"
    assert reranker["profiles"] == ["reranker"]
    assert reranker["volumes"] == ["reranker-model-cache:/models"]
    assert "reranker-model-cache" in compose["volumes"]

    api_environment = compose["services"]["api"]["environment"]
    assert api_environment["COMPANY_LENS_RERANKER_PROVIDER"] == (
        "${COMPANY_LENS_RERANKER_PROVIDER:-noop}"
    )
    assert api_environment["COMPANY_LENS_RERANKER_URL"] == (
        "${COMPANY_LENS_RERANKER_URL:-http://reranker:8080}"
    )
    assert api_environment["COMPANY_LENS_RERANKER_TIMEOUT_SECONDS"] == (
        "${COMPANY_LENS_RERANKER_TIMEOUT_SECONDS:-2.0}"
    )
    assert api_environment["COMPANY_LENS_RERANKER_FAIL_CLOSED"] == (
        "${COMPANY_LENS_RERANKER_FAIL_CLOSED:-false}"
    )
