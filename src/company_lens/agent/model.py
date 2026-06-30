from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from company_lens.agent.schemas import AgentError
from company_lens.prompts import PromptMetadata

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class ModelPurpose(enum.StrEnum):
    PARSE = "parse"
    ENTITY_EXTRACTION = "entity_extraction"
    PLAN = "plan"
    ANSWER = "answer"
    VALIDATE = "validate"
    REPAIR = "repair"


class ModelMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)
    prompt: PromptMetadata | None = None

    @field_validator("content")
    @classmethod
    def content_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Model message content cannot be blank.")
        return value


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class StructuredModelResult[OutputT: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    response_id: str
    output: OutputT | None = None
    refusal: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)

    @model_validator(mode="after")
    def validate_result(self) -> StructuredModelResult[OutputT]:
        if (self.output is None) == (self.refusal is None):
            raise ValueError("Exactly one of output or refusal is required.")
        return self


class TextModelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    response_id: str
    text: str | None = None
    refusal: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)

    @model_validator(mode="after")
    def validate_result(self) -> TextModelResult:
        if (self.text is None) == (self.refusal is None):
            raise ValueError("Exactly one of text or refusal is required.")
        if self.text is not None and not self.text.strip():
            raise ValueError("Model text output cannot be blank.")
        return self


class ResearchModelProvider(Protocol):
    def generate_structured(
        self,
        messages: Sequence[ModelMessage],
        output_type: type[StructuredOutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[StructuredOutputT]: ...

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult: ...


class ModelProviderError(RuntimeError):
    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)
