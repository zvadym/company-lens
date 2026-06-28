from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Keep allowed values explicit so dataset authors cannot accidentally invent adapter-specific terms.
CaseCategory = Literal[
    "document_retrieval",
    "structured_financial",
    "hybrid",
    "cross_document_comparison",
    "ambiguous_entity",
    "missing_data_or_abstention",
    "adversarial_or_prompt_injection",
    "follow_up",
]
ConversationRole = Literal["user", "assistant"]
CompanyResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]
CompanyTargetSource = Literal["current_question", "follow_up_context", "prepared_ticker"]
FollowUpInheritance = Literal["companies", "metrics", "operation"]
FollowUpAddition = Literal["chart"]
ExpectedRoute = Literal[
    "rag_only",
    "structured_only",
    "api_only",
    "calculation",
    "hybrid",
    "unsupported",
]
ExpectedTool = Literal[
    "retrieve_documents",
    "query_financial_facts",
    "query_macro_series",
    "calculate_metrics",
    "generate_chart_spec",
    "validate_citations",
]


class GoldenModel(BaseModel):
    # Evaluation cases should fail closed when unknown fields appear in YAML.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConversationTurn(GoldenModel):
    role: ConversationRole
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return _clean_text(value)


class ExpectedCompany(GoldenModel):
    mention: str = Field(min_length=1)
    status: CompanyResolutionStatus
    ticker: str | None = None
    source: CompanyTargetSource

    @field_validator("mention")
    @classmethod
    def normalize_mention(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        ticker = value.strip().upper().removeprefix("$")
        if not ticker:
            return None
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", ticker):
            raise ValueError("ticker must be a concise market symbol")
        return ticker

    @model_validator(mode="after")
    def validate_resolution(self) -> ExpectedCompany:
        # Resolved companies need stable public-market handles; unresolved mentions do not.
        if self.status == "resolved" and self.ticker is None:
            raise ValueError("resolved companies require a ticker")
        if self.status == "unresolved" and self.ticker is not None:
            raise ValueError("unresolved companies must not define a ticker")
        return self


class CompanyReplacement(GoldenModel):
    from_: tuple[str, ...] = Field(default=(), alias="from")
    to: tuple[str, ...] = ()

    @field_validator("from_", "to")
    @classmethod
    def normalize_company_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_cleaned(values)

    @model_validator(mode="after")
    def validate_replacement(self) -> CompanyReplacement:
        if not self.from_ or not self.to:
            raise ValueError("company replacement requires both from and to companies")
        return self


class FollowUpExpectation(GoldenModel):
    inherit: tuple[FollowUpInheritance, ...] = ()
    add: tuple[FollowUpAddition, ...] = ()
    replace_companies: CompanyReplacement | None = None
    add_companies: tuple[str, ...] = ()
    prohibited_companies: tuple[str, ...] = ()
    must_not_reuse_previous_company: bool = False
    must_not_resolve_terms_as_company: tuple[str, ...] = ()

    @field_validator("inherit")
    @classmethod
    def validate_unique_inheritance(
        cls,
        values: tuple[FollowUpInheritance, ...],
    ) -> tuple[FollowUpInheritance, ...]:
        return _unique_values(values)

    @field_validator("add")
    @classmethod
    def validate_unique_additions(
        cls,
        values: tuple[FollowUpAddition, ...],
    ) -> tuple[FollowUpAddition, ...]:
        return _unique_values(values)

    @field_validator(
        "add_companies",
        "prohibited_companies",
        "must_not_resolve_terms_as_company",
    )
    @classmethod
    def normalize_text_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_cleaned(values)

    @model_validator(mode="after")
    def validate_safety_expectations(self) -> FollowUpExpectation:
        # If prior-company reuse is forbidden, the old target must be named for evaluator checks.
        if self.must_not_reuse_previous_company and not self.prohibited_companies:
            raise ValueError(
                "must_not_reuse_previous_company requires at least one prohibited company"
            )
        return self


class RouteExpectation(GoldenModel):
    expected_route: ExpectedRoute
    required_tools: tuple[ExpectedTool, ...] = ()
    prohibited_tools: tuple[ExpectedTool, ...] = ()

    @field_validator("required_tools", "prohibited_tools")
    @classmethod
    def validate_unique_tools(cls, values: tuple[ExpectedTool, ...]) -> tuple[ExpectedTool, ...]:
        return _unique_values(values)

    @model_validator(mode="after")
    def validate_tool_sets(self) -> RouteExpectation:
        # Required/prohibited overlap would make a case impossible to satisfy.
        overlap = set(self.required_tools) & set(self.prohibited_tools)
        if overlap:
            formatted = ", ".join(sorted(overlap))
            raise ValueError(f"tools cannot be both required and prohibited: {formatted}")
        return self


class ExpectedBehavior(GoldenModel):
    companies: tuple[ExpectedCompany, ...] = Field(min_length=1)
    metrics: tuple[str, ...] = ()
    operation: str | None = None
    follow_up: FollowUpExpectation | None = None
    route: RouteExpectation

    @field_validator("metrics")
    @classmethod
    def normalize_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_identifier_values(values)

    @field_validator("operation")
    @classmethod
    def normalize_optional_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not re.fullmatch(r"[a-z][a-z0-9_]*", cleaned):
            raise ValueError("operation must use lowercase snake_case")
        return cleaned


class GoldenDatasetCase(GoldenModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*_[0-9]{3}$")
    category: CaseCategory
    conversation: tuple[ConversationTurn, ...] = Field(min_length=1)
    expected: ExpectedBehavior
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value)

    @model_validator(mode="after")
    def validate_case_shape(self) -> GoldenDatasetCase:
        # Multi-turn memory cases need enough conversation history to evaluate inheritance.
        if self.category == "follow_up":
            user_turns = [turn for turn in self.conversation if turn.role == "user"]
            if len(user_turns) < 2:
                raise ValueError("follow_up cases require at least two user turns")
            if self.expected.follow_up is None:
                raise ValueError("follow_up cases require follow_up expectations")
        return self


class GoldenDataset(GoldenModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9\-]*$")
    version: int = Field(ge=1)
    description: str | None = None
    cases: tuple[GoldenDatasetCase, ...] = Field(min_length=1)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> GoldenDataset:
        # Case IDs are stable handles used by reports, annotations, and future adapter exports.
        case_ids = [case.id for case in self.cases]
        duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {', '.join(duplicates)}")
        return self


def load_golden_dataset(path: Path) -> GoldenDataset:
    # YAML stays as the authoring format; Pydantic is the validation boundary.
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Golden dataset must be a YAML mapping.")
    return GoldenDataset.model_validate(payload)


def validate_golden_dataset(path: Path) -> GoldenDataset:
    return load_golden_dataset(path)


def _clean_text(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("text values cannot be blank")
    return cleaned


def _unique_cleaned(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_clean_text(value) for value in values))


def _unique_values[ValueT](values: tuple[ValueT, ...]) -> tuple[ValueT, ...]:
    return tuple(dict.fromkeys(values))


def _unique_identifier_values(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = _unique_cleaned(values)
    invalid = [value for value in cleaned if not re.fullmatch(r"[a-z][a-z0-9_]*", value)]
    if invalid:
        formatted = ", ".join(invalid)
        raise ValueError(f"values must use lowercase snake_case identifiers: {formatted}")
    return cleaned


def golden_dataset_summary(dataset: GoldenDataset) -> dict[str, Any]:
    # CLI output is intentionally compact so it can be read in CI logs.
    categories: dict[str, int] = {}
    for case in dataset.cases:
        categories[case.category] = categories.get(case.category, 0) + 1
    return {
        "name": dataset.name,
        "version": dataset.version,
        "cases": len(dataset.cases),
        "categories": categories,
    }
