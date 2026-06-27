from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.responses import EasyInputMessageParam, ResponseInputParam
from openai.types.shared_params import Reasoning
from pydantic import BaseModel

from company_lens.agent.model import (
    ModelMessage,
    ModelProviderError,
    ModelPurpose,
    ModelUsage,
    StructuredModelResult,
    StructuredOutputT,
    TextModelResult,
)
from company_lens.agent.schemas import AgentError, AgentErrorCategory, AgentErrorSeverity
from company_lens.config import Settings
from company_lens.observability.telemetry import (
    TraceContentPolicy,
    observe_operation,
    record_generation,
)
from company_lens.reliability import (
    CircuitBreaker,
    CircuitOpenError,
    RetryPolicy,
    call_with_resilience,
)

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]


class OpenAIResearchModelProvider:
    def __init__(
        self,
        *,
        api_key: str,
        planning_model: str = "gpt-5.4-mini",
        answer_model: str = "gpt-5.5",
        repair_model: str = "gpt-5.4-mini",
        validation_model: str = "gpt-5.4-mini",
        planning_reasoning_effort: ReasoningEffort = "low",
        answer_reasoning_effort: ReasoningEffort = "medium",
        repair_reasoning_effort: ReasoningEffort = "low",
        validation_reasoning_effort: ReasoningEffort = "low",
        planning_max_output_tokens: int = 2_000,
        answer_max_output_tokens: int = 8_000,
        repair_max_output_tokens: int = 3_000,
        validation_max_output_tokens: int = 512,
        timeout_seconds: float = 30.0,
        repair_timeout_seconds: float = 30.0,
        max_retries: int = 0,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
        trace_content: TraceContentPolicy = "metadata",
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("An OpenAI API key is required.")
        if (
            planning_max_output_tokens <= 0
            or answer_max_output_tokens <= 0
            or repair_max_output_tokens <= 0
            or validation_max_output_tokens <= 0
        ):
            raise ValueError("Model output token limits must be positive.")
        self._planning_model = planning_model
        self._answer_model = answer_model
        self._repair_model = repair_model
        self._validation_model = validation_model
        self._planning_reasoning_effort = planning_reasoning_effort
        self._answer_reasoning_effort = answer_reasoning_effort
        self._repair_reasoning_effort = repair_reasoning_effort
        self._validation_reasoning_effort = validation_reasoning_effort
        self._planning_max_output_tokens = planning_max_output_tokens
        self._answer_max_output_tokens = answer_max_output_tokens
        self._repair_max_output_tokens = repair_max_output_tokens
        self._validation_max_output_tokens = validation_max_output_tokens
        self._timeout_seconds = timeout_seconds
        self._repair_timeout_seconds = repair_timeout_seconds
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_seconds=circuit_breaker_recovery_seconds,
        )
        self._single_attempt = RetryPolicy(max_attempts=1)
        self._trace_content = trace_content
        self._client = client or OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def generate_structured(
        self,
        messages: Sequence[ModelMessage],
        output_type: type[StructuredOutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[StructuredOutputT]:
        model, reasoning_effort, max_output_tokens = self._configuration(purpose)
        input_items = _message_input(messages)
        try:
            with observe_operation(
                "model.generate_structured",
                kind="model",
                attributes={
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": model,
                    "company_lens.model.purpose": purpose.value,
                },
            ):
                response = call_with_resilience(
                    lambda: self._client.responses.parse(
                        model=model,
                        input=input_items,
                        text_format=output_type,
                        reasoning=Reasoning(effort=reasoning_effort),
                        max_output_tokens=max_output_tokens,
                        store=False,
                    ),
                    provider="openai",
                    retry_policy=self._single_attempt,
                    circuit_breaker=self._circuit_breaker,
                    retry_if=_retryable_provider_error,
                )
                usage = _response_usage(response)
                response_model = _response_model(response, model)
                response_id = _optional_response_id(response)
                refusal = _response_refusal(response)
                output = getattr(response, "output_parsed", None)
                record_generation(
                    model=response_model,
                    purpose=purpose.value,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    trace_content=self._trace_content,
                    input_payload=_messages_payload(messages),
                    output_payload=_structured_output_payload(output, refusal=refusal),
                    response_id=response_id,
                    model_parameters={
                        "reasoning_effort": reasoning_effort,
                        "max_output_tokens": max_output_tokens,
                    },
                )
        except Exception as exc:
            raise _map_provider_error(exc) from None

        refusal = _response_refusal(response)
        output = getattr(response, "output_parsed", None)
        if refusal is not None:
            return StructuredModelResult[StructuredOutputT](
                model=_response_model(response, model),
                response_id=_response_id(response),
                refusal=refusal,
                usage=usage,
            )
        if not isinstance(output, output_type):
            raise _invalid_response_error("OpenAI returned no parsed structured output.")
        return StructuredModelResult[StructuredOutputT](
            model=_response_model(response, model),
            response_id=_response_id(response),
            output=output,
            usage=usage,
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        model, reasoning_effort, max_output_tokens = self._configuration(purpose)
        input_items = _message_input(messages)
        try:
            request_timeout = (
                self._repair_timeout_seconds
                if purpose is ModelPurpose.REPAIR
                else self._timeout_seconds
            )
            with observe_operation(
                "model.generate_text",
                kind="model",
                attributes={
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": model,
                    "company_lens.model.purpose": purpose.value,
                },
            ):
                response = call_with_resilience(
                    lambda: self._client.responses.create(
                        model=model,
                        input=input_items,
                        reasoning=Reasoning(effort=reasoning_effort),
                        max_output_tokens=max_output_tokens,
                        store=False,
                        timeout=request_timeout,
                    ),
                    provider="openai",
                    retry_policy=self._single_attempt,
                    circuit_breaker=self._circuit_breaker,
                    retry_if=_retryable_provider_error,
                )
                usage = _response_usage(response)
                response_model = _response_model(response, model)
                response_id = _optional_response_id(response)
                refusal = _response_refusal(response)
                text = getattr(response, "output_text", None)
                record_generation(
                    model=response_model,
                    purpose=purpose.value,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    total_tokens=usage.total_tokens,
                    trace_content=self._trace_content,
                    input_payload=_messages_payload(messages),
                    output_payload=_text_output_payload(text, refusal=refusal),
                    response_id=response_id,
                    model_parameters={
                        "reasoning_effort": reasoning_effort,
                        "max_output_tokens": max_output_tokens,
                    },
                )
        except Exception as exc:
            raise _map_provider_error(exc) from None

        refusal = _response_refusal(response)
        text = getattr(response, "output_text", None)
        if refusal is not None:
            return TextModelResult(
                model=_response_model(response, model),
                response_id=_response_id(response),
                refusal=refusal,
                usage=usage,
            )
        if not isinstance(text, str) or not text.strip():
            raise _invalid_response_error("OpenAI returned no text output.")
        return TextModelResult(
            model=_response_model(response, model),
            response_id=_response_id(response),
            text=text,
            usage=usage,
        )

    def _configuration(self, purpose: ModelPurpose) -> tuple[str, ReasoningEffort, int]:
        if purpose in {
            ModelPurpose.PARSE,
            ModelPurpose.ENTITY_EXTRACTION,
            ModelPurpose.PLAN,
        }:
            return (
                self._planning_model,
                self._planning_reasoning_effort,
                self._planning_max_output_tokens,
            )
        if purpose is ModelPurpose.VALIDATE:
            return (
                self._validation_model,
                self._validation_reasoning_effort,
                self._validation_max_output_tokens,
            )
        if purpose is ModelPurpose.REPAIR:
            return (
                self._repair_model,
                self._repair_reasoning_effort,
                self._repair_max_output_tokens,
            )
        return (
            self._answer_model,
            self._answer_reasoning_effort,
            self._answer_max_output_tokens,
        )


def build_openai_model_provider(settings: Settings) -> OpenAIResearchModelProvider:
    if settings.openai_api_key is None:
        raise ValueError("OPENAI_API_KEY is required for the OpenAI model provider.")
    return OpenAIResearchModelProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        planning_model=settings.openai_planning_model,
        answer_model=settings.openai_answer_model,
        repair_model=settings.openai_repair_model,
        validation_model=settings.semantic_judge_model,
        planning_reasoning_effort=settings.openai_planning_reasoning_effort,
        answer_reasoning_effort=settings.openai_answer_reasoning_effort,
        repair_reasoning_effort=settings.openai_repair_reasoning_effort,
        validation_reasoning_effort=settings.semantic_judge_reasoning_effort,
        planning_max_output_tokens=settings.openai_planning_max_output_tokens,
        answer_max_output_tokens=settings.openai_answer_max_output_tokens,
        repair_max_output_tokens=settings.openai_repair_max_output_tokens,
        validation_max_output_tokens=settings.semantic_judge_max_output_tokens,
        timeout_seconds=settings.openai_request_timeout_seconds,
        repair_timeout_seconds=settings.openai_repair_timeout_seconds,
        # Workflow retries are observable and budgeted. Retrying inside the SDK as well would
        # multiply worst-case latency and hide attempts from the execution trace.
        max_retries=0,
        circuit_breaker_failure_threshold=settings.circuit_breaker_failure_threshold,
        circuit_breaker_recovery_seconds=settings.circuit_breaker_recovery_seconds,
        trace_content=settings.trace_content,
    )


def _message_input(messages: Sequence[ModelMessage]) -> ResponseInputParam:
    if not messages:
        raise _error(
            AgentErrorCategory.VALIDATION,
            AgentErrorSeverity.TERMINAL,
            "empty_model_messages",
            "At least one model message is required.",
        )
    result: ResponseInputParam = [
        EasyInputMessageParam(role=message.role, content=message.content) for message in messages
    ]
    return result


def _messages_payload(messages: Sequence[ModelMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _response_refusal(response: Any) -> str | None:
    for output in getattr(response, "output", ()):
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                refusal = getattr(content, "refusal", None)
                if isinstance(refusal, str) and refusal.strip():
                    return refusal
    return None


def _response_usage(response: Any) -> ModelUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return ModelUsage()
    return ModelUsage(
        input_tokens=_nonnegative_int(getattr(usage, "input_tokens", 0)),
        output_tokens=_nonnegative_int(getattr(usage, "output_tokens", 0)),
        total_tokens=_nonnegative_int(getattr(usage, "total_tokens", 0)),
    )


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _response_model(response: Any, fallback: str) -> str:
    model = getattr(response, "model", None)
    return model if isinstance(model, str) and model else fallback


def _response_id(response: Any) -> str:
    response_id = getattr(response, "id", None)
    if not isinstance(response_id, str) or not response_id:
        raise _invalid_response_error("OpenAI returned no response ID.")
    return response_id


def _optional_response_id(response: Any) -> str | None:
    response_id = getattr(response, "id", None)
    return response_id if isinstance(response_id, str) and response_id else None


def _structured_output_payload(output: Any, *, refusal: str | None) -> object:
    if refusal is not None:
        return {"refusal": refusal}
    if isinstance(output, BaseModel):
        return output.model_dump(mode="json")
    return {"output_type": type(output).__name__}


def _text_output_payload(text: object, *, refusal: str | None) -> object:
    if refusal is not None:
        return {"refusal": refusal}
    return text if isinstance(text, str) else {"output_type": type(text).__name__}


def _map_provider_error(exc: Exception) -> ModelProviderError:
    if isinstance(exc, CircuitOpenError):
        return _error(
            AgentErrorCategory.PROVIDER_SERVICE,
            AgentErrorSeverity.RECOVERABLE,
            "openai_circuit_open",
            "OpenAI is temporarily unavailable after repeated failures.",
        )
    if isinstance(exc, APITimeoutError):
        return _error(
            AgentErrorCategory.PROVIDER_TIMEOUT,
            AgentErrorSeverity.RECOVERABLE,
            "openai_timeout",
            "OpenAI request timed out.",
        )
    if isinstance(exc, RateLimitError):
        return _error(
            AgentErrorCategory.PROVIDER_RATE_LIMIT,
            AgentErrorSeverity.RECOVERABLE,
            "openai_rate_limit",
            "OpenAI rate limit was exceeded.",
        )
    if isinstance(exc, APIConnectionError):
        return _error(
            AgentErrorCategory.PROVIDER_CONNECTION,
            AgentErrorSeverity.RECOVERABLE,
            "openai_connection",
            "OpenAI connection failed.",
        )
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return _error(
            AgentErrorCategory.PROVIDER_AUTH,
            AgentErrorSeverity.TERMINAL,
            "openai_auth",
            "OpenAI authentication or permission check failed.",
        )
    if isinstance(exc, BadRequestError):
        return _error(
            AgentErrorCategory.PROVIDER_RESPONSE,
            AgentErrorSeverity.TERMINAL,
            "openai_bad_request",
            "OpenAI rejected the model request.",
        )
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return _error(
            AgentErrorCategory.PROVIDER_SERVICE,
            AgentErrorSeverity.RECOVERABLE,
            "openai_service",
            "OpenAI service returned a transient error.",
        )
    return _error(
        AgentErrorCategory.INTERNAL,
        AgentErrorSeverity.TERMINAL,
        "openai_unexpected",
        "Unexpected OpenAI provider failure.",
    )


def _retryable_provider_error(exc: Exception) -> bool:
    return isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)) or (
        isinstance(exc, APIStatusError) and exc.status_code >= 500
    )


def _invalid_response_error(message: str) -> ModelProviderError:
    return _error(
        AgentErrorCategory.PROVIDER_RESPONSE,
        AgentErrorSeverity.TERMINAL,
        "openai_invalid_response",
        message,
    )


def _error(
    category: AgentErrorCategory,
    severity: AgentErrorSeverity,
    code: str,
    message: str,
) -> ModelProviderError:
    return ModelProviderError(
        AgentError(
            category=category,
            severity=severity,
            code=code,
            message=message,
        )
    )
