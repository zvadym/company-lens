from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, BadRequestError, RateLimitError
from pydantic import BaseModel

from company_lens.agent.model import (
    ModelMessage,
    ModelProviderError,
    ModelPurpose,
    ResearchModelProvider,
)
from company_lens.agent.openai_provider import OpenAIResearchModelProvider
from company_lens.agent.schemas import AgentErrorCategory, AgentErrorSeverity


class ParsedIntent(BaseModel):
    intent: str


class FakeResponses:
    def __init__(self) -> None:
        self.parse_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.parse_response: Any = _response(output_parsed=ParsedIntent(intent="financial"))
        self.create_response: Any = _response(output_text="Grounded answer")
        self.error: Exception | None = None

    def parse(self, **kwargs: Any) -> Any:
        self.parse_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.parse_response

    def create(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.create_response


@pytest.mark.parametrize(
    "purpose",
    [ModelPurpose.PARSE, ModelPurpose.ENTITY_EXTRACTION, ModelPurpose.PLAN],
)
def test_structured_generation_uses_planning_model_and_stateless_parse(
    purpose: ModelPurpose,
) -> None:
    responses = FakeResponses()
    provider: ResearchModelProvider = _provider(responses)

    result = provider.generate_structured(
        _messages(),
        ParsedIntent,
        purpose=purpose,
    )

    assert result.output == ParsedIntent(intent="financial")
    assert result.usage.total_tokens == 15
    assert responses.parse_calls == [
        {
            "model": "planning-model",
            "input": [
                {"role": "system", "content": "Classify the question."},
                {"role": "user", "content": "Cloudflare revenue growth"},
            ],
            "text_format": ParsedIntent,
            "reasoning": {"effort": "low"},
            "max_output_tokens": 111,
            "store": False,
        }
    ]


def test_semantic_validation_uses_dedicated_judge_configuration() -> None:
    responses = FakeResponses()
    provider = _provider(responses)

    provider.generate_structured(
        _messages(),
        ParsedIntent,
        purpose=ModelPurpose.VALIDATE,
    )

    assert responses.parse_calls[0]["model"] == "validation-model"
    assert responses.parse_calls[0]["reasoning"] == {"effort": "low"}
    assert responses.parse_calls[0]["max_output_tokens"] == 333


@pytest.mark.parametrize("purpose", [ModelPurpose.ANSWER, ModelPurpose.REPAIR])
def test_text_generation_uses_answer_model_without_reasoning_output(
    purpose: ModelPurpose,
) -> None:
    responses = FakeResponses()
    provider = _provider(responses)

    result = provider.generate_text(_messages(), purpose=purpose)

    assert result.text == "Grounded answer"
    assert result.model == "response-model"
    assert result.model_dump().keys() == {"model", "response_id", "text", "refusal", "usage"}
    assert responses.create_calls[0]["store"] is False
    assert "previous_response_id" not in responses.create_calls[0]
    if purpose is ModelPurpose.REPAIR:
        assert responses.create_calls[0]["model"] == "repair-model"
        assert responses.create_calls[0]["reasoning"] == {"effort": "low"}
        assert responses.create_calls[0]["max_output_tokens"] == 444
        assert responses.create_calls[0]["timeout"] == 30.0
    else:
        assert responses.create_calls[0]["model"] == "answer-model"
        assert responses.create_calls[0]["reasoning"] == {"effort": "medium"}
        assert responses.create_calls[0]["max_output_tokens"] == 222
        assert responses.create_calls[0]["timeout"] == 30.0


def test_refusal_is_a_typed_result() -> None:
    responses = FakeResponses()
    responses.parse_response = _response(
        output_parsed=None,
        output=(
            SimpleNamespace(content=(SimpleNamespace(type="refusal", refusal="Cannot answer."),)),
        ),
    )

    result = _provider(responses).generate_structured(
        _messages(),
        ParsedIntent,
        purpose=ModelPurpose.PLAN,
    )

    assert result.output is None
    assert result.refusal == "Cannot answer."


def test_empty_output_is_a_terminal_typed_error() -> None:
    responses = FakeResponses()
    responses.create_response = _response(output_text="")

    with pytest.raises(ModelProviderError) as raised:
        _provider(responses).generate_text(_messages(), purpose=ModelPurpose.ANSWER)

    assert raised.value.error.category is AgentErrorCategory.PROVIDER_RESPONSE
    assert raised.value.error.severity is AgentErrorSeverity.TERMINAL
    assert raised.value.error.code == "openai_invalid_response"


def test_missing_structured_output_is_a_terminal_typed_error() -> None:
    responses = FakeResponses()
    responses.parse_response = _response(output_parsed=None)

    with pytest.raises(ModelProviderError) as raised:
        _provider(responses).generate_structured(
            _messages(), ParsedIntent, purpose=ModelPurpose.PARSE
        )

    assert raised.value.error.category is AgentErrorCategory.PROVIDER_RESPONSE
    assert raised.value.error.severity is AgentErrorSeverity.TERMINAL


@pytest.mark.parametrize(
    ("exception", "category", "severity"),
    [
        (
            APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")),
            AgentErrorCategory.PROVIDER_TIMEOUT,
            AgentErrorSeverity.RECOVERABLE,
        ),
        (
            RateLimitError(
                "rate limit",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            AgentErrorCategory.PROVIDER_RATE_LIMIT,
            AgentErrorSeverity.RECOVERABLE,
        ),
        (
            AuthenticationError(
                "bad secret-key-value",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            AgentErrorCategory.PROVIDER_AUTH,
            AgentErrorSeverity.TERMINAL,
        ),
        (
            BadRequestError(
                "invalid schema secret-key-value",
                response=httpx.Response(
                    400,
                    request=httpx.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            AgentErrorCategory.PROVIDER_RESPONSE,
            AgentErrorSeverity.TERMINAL,
        ),
    ],
)
def test_provider_errors_are_typed_and_sanitized(
    exception: Exception,
    category: AgentErrorCategory,
    severity: AgentErrorSeverity,
) -> None:
    responses = FakeResponses()
    responses.error = exception

    with pytest.raises(ModelProviderError) as raised:
        _provider(responses).generate_text(_messages(), purpose=ModelPurpose.ANSWER)

    assert raised.value.error.category is category
    assert raised.value.error.severity is severity
    assert "secret-key-value" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_empty_messages_fail_before_the_provider_call() -> None:
    responses = FakeResponses()

    with pytest.raises(ModelProviderError) as raised:
        _provider(responses).generate_text((), purpose=ModelPurpose.ANSWER)

    assert raised.value.error.category is AgentErrorCategory.VALIDATION
    assert responses.create_calls == []


def _provider(responses: FakeResponses) -> OpenAIResearchModelProvider:
    return OpenAIResearchModelProvider(
        api_key="test-key",
        planning_model="planning-model",
        answer_model="answer-model",
        repair_model="repair-model",
        validation_model="validation-model",
        planning_max_output_tokens=111,
        answer_max_output_tokens=222,
        repair_max_output_tokens=444,
        validation_max_output_tokens=333,
        client=SimpleNamespace(responses=responses),
    )


def _messages() -> tuple[ModelMessage, ...]:
    return (
        ModelMessage(role="system", content="Classify the question."),
        ModelMessage(role="user", content="Cloudflare revenue growth"),
    )


def _response(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": "resp_test",
        "model": "response-model",
        "output": (),
        "output_parsed": None,
        "output_text": "",
        "usage": SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
    }
    values.update(overrides)
    return SimpleNamespace(**values)
