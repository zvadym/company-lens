from __future__ import annotations

from typing import Any

from company_lens.config import Settings
from company_lens.prompt_sync import sync_prompts_to_langfuse


def test_prompt_sync_dry_run_lists_repo_prompts() -> None:
    results = sync_prompts_to_langfuse(Settings(), dry_run=True)

    names = {result.name for result in results}
    assert "agent/parse-question" in names
    assert "processing/document-summary" in names
    assert {result.status for result in results} == {"dry_run"}


def test_prompt_sync_uploads_text_prompts_to_langfuse_client() -> None:
    client = FakePromptClient()

    results = sync_prompts_to_langfuse(Settings(), client=client, label="production")

    assert len(client.created) == len(results)
    parse_prompt = next(item for item in client.created if item["name"] == "agent/parse-question")
    assert parse_prompt["labels"] == ["production"]
    assert parse_prompt["type"] == "text"
    assert parse_prompt["config"]["repo_version"] == "research-v1"
    assert parse_prompt["prompt"].startswith("Classify a public-company research question")


class FakePromptClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create_prompt(self, **kwargs: Any) -> object:
        self.created.append(kwargs)
        return type("CreatedPrompt", (), {"version": len(self.created)})()
