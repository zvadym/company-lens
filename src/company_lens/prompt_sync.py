from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from company_lens.config import Settings, get_settings
from company_lens.prompts import RepoPromptProvider


class PromptSyncResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    content_hash: str
    label: str
    status: str
    langfuse_version: int | None = None


def sync_prompts_to_langfuse(
    settings: Settings,
    *,
    label: str | None = None,
    dry_run: bool = False,
    client: Any | None = None,
) -> tuple[PromptSyncResult, ...]:
    provider = RepoPromptProvider(settings.prompt_manifest_path)
    prompt_label = label or settings.langfuse_prompt_label
    if client is None and not dry_run:
        if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
            raise PromptSyncError("Langfuse prompt sync requires Langfuse credentials.")
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
        )
    results: list[PromptSyncResult] = []
    for prompt in provider.list_text():
        if dry_run:
            results.append(
                PromptSyncResult(
                    name=prompt.name,
                    version=prompt.metadata.version,
                    content_hash=prompt.metadata.content_hash,
                    label=prompt_label,
                    status="dry_run",
                )
            )
            continue
        assert client is not None
        created = client.create_prompt(
            name=prompt.name,
            prompt=prompt.content,
            type="text",
            labels=[prompt_label],
            config={
                "repo_version": prompt.metadata.version,
                "repo_content_hash": prompt.metadata.content_hash,
            },
            commit_message=f"Sync {prompt.metadata.version} from repository fallback",
        )
        results.append(
            PromptSyncResult(
                name=prompt.name,
                version=prompt.metadata.version,
                content_hash=prompt.metadata.content_hash,
                label=prompt_label,
                status="synced",
                langfuse_version=_int_or_none(getattr(created, "version", None)),
            )
        )
    return tuple(results)


class PromptSyncError(RuntimeError):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m company_lens.prompt_sync")
    parser.add_argument("--label", default=None, help="Langfuse label to assign.")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without uploading.")
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        results = sync_prompts_to_langfuse(settings, label=args.label, dry_run=args.dry_run)
    except PromptSyncError as exc:
        print(f"Prompt sync failed: {exc}")
        return 1
    print(json.dumps([result.model_dump(mode="json") for result in results], indent=2))
    return 0


def _int_or_none(value: object) -> int | None:
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
