from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CalculationOperation = Literal[
    "quarter_over_quarter_growth",
    "year_over_year_growth",
    "cagr",
    "margin",
    "absolute_change",
    "percentage_change",
    "rolling_average",
    "normalised_index",
    "correlation",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ModelCalculationIntent(_FrozenModel):
    """Provider-facing calculation intent with JSON Schema number fields."""

    operation: CalculationOperation
    metrics: tuple[str, ...] = ()
    window: int | None = Field(default=None, ge=1)
    years: float | None = Field(default=None, gt=0)
    base: float | None = Field(default=None, gt=0)

    @field_validator("metrics")
    @classmethod
    def normalize_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_metrics(values)

    @model_validator(mode="after")
    def validate_scalars(self) -> ModelCalculationIntent:
        _validate_scalar_applicability(
            self.operation,
            window=self.window,
            years=self.years,
            base=self.base,
        )
        return self


class CalculationIntent(_FrozenModel):
    operation: CalculationOperation
    metrics: tuple[str, ...] = ()
    window: int | None = Field(default=None, ge=1)
    years: Decimal | None = Field(default=None, gt=0)
    base: Decimal | None = Field(default=None, gt=0)

    @field_validator("metrics")
    @classmethod
    def normalize_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_metrics(values)

    @model_validator(mode="after")
    def validate_scalars(self) -> CalculationIntent:
        _validate_scalar_applicability(
            self.operation,
            window=self.window,
            years=self.years,
            base=self.base,
        )
        return self


class BranchOperationDecision(_FrozenModel):
    branch_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operation: CalculationOperation
    window: int | None = Field(default=None, ge=1)
    years: float | None = Field(default=None, gt=0)
    base: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_scalars(self) -> BranchOperationDecision:
        _validate_scalar_applicability(
            self.operation,
            window=self.window,
            years=self.years,
            base=self.base,
        )
        return self


class OperationReconciliation(_FrozenModel):
    branch_operations: tuple[BranchOperationDecision, ...] = ()


def domain_calculation_intent(intent: ModelCalculationIntent) -> CalculationIntent:
    return CalculationIntent(
        operation=intent.operation,
        metrics=intent.metrics,
        window=intent.window,
        years=Decimal(str(intent.years)) if intent.years is not None else None,
        base=Decimal(str(intent.base)) if intent.base is not None else None,
    )


def _normalized_metrics(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(" ".join(value.split()) for value in values)
    if any(not value for value in normalized):
        raise ValueError("calculation intent metrics cannot be blank")
    if len(normalized) != len(set(normalized)):
        raise ValueError("calculation intent metrics must be unique")
    return normalized


def _validate_scalar_applicability(
    operation: CalculationOperation,
    *,
    window: int | None,
    years: float | Decimal | None,
    base: float | Decimal | None,
) -> None:
    # Source-selection periods are intentionally separate from calculation parameters.
    if operation == "rolling_average":
        if window is None or years is not None or base is not None:
            raise ValueError("rolling_average requires only window")
        return
    if operation == "cagr":
        if years is None or window is not None or base is not None:
            raise ValueError("cagr requires only years")
        return
    if operation == "normalised_index":
        if window is not None or years is not None:
            raise ValueError("normalised_index accepts only an optional base")
        return
    if window is not None or years is not None or base is not None:
        raise ValueError(f"{operation} does not accept scalar parameters")


__all__ = (
    "BranchOperationDecision",
    "CalculationIntent",
    "CalculationOperation",
    "ModelCalculationIntent",
    "OperationReconciliation",
    "domain_calculation_intent",
)
