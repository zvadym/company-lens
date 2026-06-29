from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _generate_structured_with_retries[OutputT: BaseModel](
    provider: ResearchModelProvider,
    messages: Sequence[ModelMessage],
    output_type: type[OutputT],
    *,
    purpose: ModelPurpose,
    max_retries: int,
    node: str,
) -> tuple[OutputT | None, int, AgentError | None]:
    attempts = 0
    for attempt in range(1, max_retries + 2):
        attempts = attempt
        try:
            result = provider.generate_structured(messages, output_type, purpose=purpose)
        except ModelProviderError as exc:
            error = exc.error.model_copy(update={"node": node, "attempt": attempt})
            if error.recoverable and attempt <= max_retries:
                continue
            return None, attempts, error
        if result.refusal is not None:
            return None, attempts, _provider_refusal(node, attempt)
        return result.output, attempts, None
    raise AssertionError("Unreachable model retry state.")


def _generate_text_with_retries(
    provider: ResearchModelProvider,
    messages: Sequence[ModelMessage],
    *,
    purpose: ModelPurpose,
    max_retries: int,
    node: str,
) -> tuple[str | None, int, AgentError | None]:
    attempts = 0
    for attempt in range(1, max_retries + 2):
        attempts = attempt
        try:
            result = provider.generate_text(messages, purpose=purpose)
        except ModelProviderError as exc:
            error = exc.error.model_copy(update={"node": node, "attempt": attempt})
            if error.recoverable and attempt <= max_retries:
                continue
            return None, attempts, error
        if result.refusal is not None:
            return None, attempts, _provider_refusal(node, attempt)
        return result.text, attempts, None
    raise AssertionError("Unreachable model retry state.")


def _model_node_update(
    node: str,
    attempts: int,
    started: float,
    error: AgentError | None,
) -> dict[str, object]:
    update: dict[str, object] = {
        "node_attempts": (NodeAttempt(node=node, attempts=attempts),),
        "trajectory": (
            _event(
                node,
                TrajectoryStatus.FAILED if error else TrajectoryStatus.COMPLETED,
                "Model operation failed." if error else "Model operation completed.",
                started,
                details={"attempts": attempts},
            ),
        ),
    }
    if error is not None:
        update["errors"] = (error,)
    return update


__all__ = ("_generate_structured_with_retries", "_generate_text_with_retries", "_model_node_update")
