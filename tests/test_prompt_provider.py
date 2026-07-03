from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from company_lens.prompts import (
    LangfusePromptProvider,
    PromptRegistryError,
    RepoPromptProvider,
    prompt_content_hash,
)


def test_repo_prompt_provider_loads_checked_in_prompt() -> None:
    provider = RepoPromptProvider()

    prompt = provider.get_text("agent/parse-question")

    assert prompt.content.startswith("Classify a public-company research question")
    assert prompt.metadata.name == "agent/parse-question"
    assert prompt.metadata.version == "research-v1"
    assert prompt.metadata.source == "repo"
    assert prompt.metadata.content_hash == prompt_content_hash(prompt.content)


def test_repo_prompt_provider_rejects_unknown_prompt(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("prompts: []\n", encoding="utf-8")
    provider = RepoPromptProvider(manifest)

    with pytest.raises(PromptRegistryError, match="not registered"):
        provider.get_text("missing")


def test_langfuse_prompt_provider_uses_remote_prompt_when_available() -> None:
    client = FakeLangfuseClient(
        SimpleNamespace(
            prompt="Remote prompt",
            version=7,
            is_fallback=False,
            compile=lambda: "Remote prompt",
        )
    )
    provider = LangfusePromptProvider(
        fallback=RepoPromptProvider(),
        public_key="pk-test",
        secret_key="sk-test",
        base_url="https://cloud.langfuse.com",
        client=client,
    )

    prompt = provider.get_text("agent/parse-question")

    assert prompt.content == "Remote prompt"
    assert prompt.metadata.source == "langfuse"
    assert prompt.metadata.version == "7"
    assert prompt.metadata.label == "production"
    assert prompt.metadata.langfuse_version == 7
    assert client.calls[0]["fallback"].startswith("Classify a public-company research question")


def test_langfuse_prompt_provider_falls_back_to_repo_prompt_on_fetch_error() -> None:
    provider = LangfusePromptProvider(
        fallback=RepoPromptProvider(),
        public_key="pk-test",
        secret_key="sk-test",
        base_url="https://cloud.langfuse.com",
        client=FakeLangfuseClient(RuntimeError("offline")),
    )

    prompt = provider.get_text("agent/parse-question")

    assert prompt.content.startswith("Classify a public-company research question")
    assert prompt.metadata.source == "repo"


class FakeLangfuseClient:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def get_prompt(self, name: str, **kwargs: Any) -> object:
        self.calls.append({"name": name, **kwargs})
        if isinstance(self._result, Exception):
            raise self._result
        return self._result
