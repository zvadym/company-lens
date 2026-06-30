from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

PromptKind = Literal["text", "chat"]
PromptSource = Literal["repo", "langfuse"]


class PromptMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source: PromptSource
    content_hash: str = Field(min_length=64, max_length=64)
    label: str | None = None
    langfuse_version: int | None = None


class ResolvedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    content: str = Field(min_length=1)
    metadata: PromptMetadata


class PromptProvider(Protocol):
    def get_text(self, name: str) -> ResolvedPrompt: ...


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    version: str
    kind: PromptKind
    path: Path


class RepoPromptProvider:
    def __init__(self, manifest_path: Path = Path("prompts/manifest.yaml")) -> None:
        self._manifest_path = manifest_path
        self._definitions = _load_manifest(manifest_path)

    def get_text(self, name: str) -> ResolvedPrompt:
        definition = self._definition(name)
        if definition.kind != "text":
            raise PromptRegistryError(f"Prompt '{name}' is not a text prompt.")
        content = _read_prompt_file(definition.path)
        return ResolvedPrompt(
            name=name,
            content=content,
            metadata=PromptMetadata(
                name=name,
                version=definition.version,
                source="repo",
                content_hash=prompt_content_hash(content),
            ),
        )

    def list_text(self) -> tuple[ResolvedPrompt, ...]:
        return tuple(
            self.get_text(name)
            for name, definition in sorted(self._definitions.items())
            if definition.kind == "text"
        )

    def _definition(self, name: str) -> PromptDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise PromptRegistryError(f"Prompt '{name}' is not registered.") from exc


class LangfusePromptProvider:
    def __init__(
        self,
        *,
        fallback: PromptProvider,
        public_key: str,
        secret_key: str,
        base_url: str,
        label: str = "production",
        cache_ttl_seconds: int = 60,
        fetch_timeout_seconds: int = 5,
        client: Any | None = None,
    ) -> None:
        self._fallback = fallback
        self._label = label
        self._cache_ttl_seconds = cache_ttl_seconds
        self._fetch_timeout_seconds = fetch_timeout_seconds
        if client is not None:
            self._client = client
        else:
            from langfuse import Langfuse

            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                base_url=base_url,
            )

    def get_text(self, name: str) -> ResolvedPrompt:
        fallback = self._fallback.get_text(name)
        try:
            prompt = self._client.get_prompt(
                name,
                label=self._label,
                type="text",
                fallback=fallback.content,
                cache_ttl_seconds=self._cache_ttl_seconds,
                fetch_timeout_seconds=self._fetch_timeout_seconds,
            )
        except Exception:
            return fallback
        content = _text_prompt_content(prompt)
        is_fallback = bool(getattr(prompt, "is_fallback", False))
        if is_fallback:
            return fallback
        return ResolvedPrompt(
            name=name,
            content=content,
            metadata=PromptMetadata(
                name=name,
                version=str(getattr(prompt, "version", fallback.metadata.version)),
                source="langfuse",
                label=self._label,
                langfuse_version=_int_or_none(getattr(prompt, "version", None)),
                content_hash=prompt_content_hash(content),
            ),
        )


class PromptRegistryError(RuntimeError):
    pass


def build_prompt_provider(settings: Any) -> PromptProvider:
    fallback = RepoPromptProvider(settings.prompt_manifest_path)
    if not settings.langfuse_prompts_enabled:
        return fallback
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        return fallback
    return LangfusePromptProvider(
        fallback=fallback,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        label=settings.langfuse_prompt_label,
        cache_ttl_seconds=settings.langfuse_prompt_cache_ttl_seconds,
        fetch_timeout_seconds=settings.langfuse_prompt_fetch_timeout_seconds,
    )


def repo_text_prompt(name: str, manifest_path: Path = Path("prompts/manifest.yaml")) -> str:
    return RepoPromptProvider(manifest_path).get_text(name).content


def prompt_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_manifest(manifest_path: Path) -> dict[str, PromptDefinition]:
    manifest = _read_yaml(manifest_path)
    raw_prompts = manifest.get("prompts")
    if not isinstance(raw_prompts, list):
        raise PromptRegistryError("Prompt manifest must contain a prompts list.")
    base_dir = manifest_path.parent
    definitions: dict[str, PromptDefinition] = {}
    for item in raw_prompts:
        definition = _definition_from_manifest_item(item, base_dir)
        if definition.name in definitions:
            raise PromptRegistryError(f"Prompt '{definition.name}' is registered twice.")
        definitions[definition.name] = definition
    return definitions


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise PromptRegistryError(f"Prompt manifest not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise PromptRegistryError("Prompt manifest must be a mapping.")
    return loaded


def _definition_from_manifest_item(item: object, base_dir: Path) -> PromptDefinition:
    if not isinstance(item, Mapping):
        raise PromptRegistryError("Prompt manifest entries must be mappings.")
    name = _required_string(item, "name")
    version = _required_string(item, "version")
    kind = _required_string(item, "type")
    path = _required_string(item, "path")
    if kind not in {"text", "chat"}:
        raise PromptRegistryError(f"Prompt '{name}' has unsupported type '{kind}'.")
    return PromptDefinition(
        name=name,
        version=version,
        kind=cast(PromptKind, kind),
        path=base_dir / path,
    )


def _required_string(item: Mapping[object, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PromptRegistryError(f"Prompt manifest entry requires '{key}'.")
    return value.strip()


def _read_prompt_file(path: Path) -> str:
    if not path.exists():
        raise PromptRegistryError(f"Prompt file not found: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise PromptRegistryError(f"Prompt file is empty: {path}")
    return content


def _text_prompt_content(prompt: Any) -> str:
    compile_prompt = getattr(prompt, "compile", None)
    if callable(compile_prompt):
        compiled = compile_prompt()
        if isinstance(compiled, str) and compiled.strip():
            return compiled
    content = getattr(prompt, "prompt", None)
    if isinstance(content, str) and content.strip():
        return content
    raise PromptRegistryError("Langfuse returned an invalid text prompt.")


def _int_or_none(value: object) -> int | None:
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
