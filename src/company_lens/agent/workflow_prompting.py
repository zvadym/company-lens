from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _system_prompt_message(
    runtime: Runtime[ResearchAgentRuntime],
    name: str,
) -> ModelMessage:
    prompt = runtime.context.prompt_provider.get_text(name)
    return ModelMessage(role="system", content=prompt.content, prompt=prompt.metadata)


__all__ = ("_system_prompt_message",)
