from __future__ import annotations

from pathlib import Path

import yaml


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
