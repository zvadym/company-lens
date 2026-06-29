from __future__ import annotations

# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *


def _fallback_calculation_period(points: Sequence[tuple[date | None, Decimal, str | None]]) -> str:
    dates = tuple(point[0] for point in points if point[0] is not None)
    if not dates:
        return "the available periods"
    first = min(dates)
    latest = max(dates)
    if first == latest:
        return first.isoformat()
    return f"{first.isoformat()} through {latest.isoformat()}"


def _payload_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except ArithmeticError:
            return None
    return None


def _payload_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _fallback_company_name(company_name: str | None) -> str:
    if company_name is None:
        return "The company"
    return company_name.replace(".", "")


def _fallback_operation_label(operation: str | None) -> str:
    return (operation or "calculation").replace("_", " ")


def _fallback_value_with_unit(
    value: str,
    unit: str,
    raw_value: Decimal | None = None,
) -> str:
    return _display_value(raw_value, unit) or f"{value} {unit}".strip()


def _fallback_display_value(value: Decimal | None, unit: str) -> str | None:
    return _display_value(value, unit)


def _display_value(value: Decimal | None, unit: str) -> str | None:
    if value is None:
        return None
    normalized_unit = unit.strip()
    unit_key = normalized_unit.casefold()
    if unit_key == "usd":
        magnitude = abs(value)
        if magnitude >= Decimal("1000000000000"):
            display = _display_decimal(value / Decimal("1000000000000"), Decimal("0.01"))
            return f"{display} trillion USD"
        if magnitude >= Decimal("1000000000"):
            return f"{_display_decimal(value / Decimal('1000000000'), Decimal('0.01'))} billion USD"
        if magnitude >= Decimal("1000000"):
            return f"{_display_decimal(value / Decimal('1000000'), Decimal('0.01'))} million USD"
        return f"{_display_decimal(value, Decimal('0.01'))} USD"
    if unit_key in {"percent", "%"}:
        return f"{_display_decimal(value, Decimal('0.01'))}%"
    display = _display_decimal(value)
    return f"{display} {normalized_unit}".strip()


def _fallback_decimal_places(value: Decimal, quantum: Decimal) -> str:
    return _display_decimal(value, quantum)


def _display_decimal(value: Decimal, quantum: Decimal | None = None) -> str:
    try:
        rounded = value.quantize(quantum) if quantum is not None else value
    except (ArithmeticError, InvalidOperation, ValueError):
        rounded = value
    normalized = format(rounded.normalize(), "f")
    sign = ""
    if normalized.startswith("-"):
        sign = "-"
        normalized = normalized[1:]
    integer, _, fractional = normalized.partition(".")
    grouped = f"{int(integer or '0'):,}"
    if fractional:
        return f"{sign}{grouped}.{fractional}"
    return f"{sign}{grouped}"


def _normalize_answer_number_formatting(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_value = match.group("value")
        try:
            value = Decimal(raw_value.replace(",", ""))
        except (ArithmeticError, InvalidOperation, ValueError):
            return match.group(0)
        return _display_value(value, match.group("unit")) or match.group(0)

    return UNIT_NUMBER_RE.sub(replace, text)


def _fallback_period(item: EvidenceEnvelope) -> str:
    if item.metadata.period_end is not None:
        return f" at {item.metadata.period_end.isoformat()}"
    if item.metadata.fiscal_year is not None:
        return f" in fiscal {item.metadata.fiscal_year}"
    return ""


def _fallback_period_value(item: EvidenceEnvelope) -> str:
    if item.metadata.period_end is not None:
        return item.metadata.period_end.isoformat()
    if item.metadata.fiscal_year is not None:
        return f"fiscal {item.metadata.fiscal_year}"
    return "available period"


def _fallback_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _display_decimal(value)


__all__ = (
    "_fallback_calculation_period",
    "_payload_decimal",
    "_payload_date",
    "_fallback_company_name",
    "_fallback_operation_label",
    "_fallback_value_with_unit",
    "_fallback_display_value",
    "_display_value",
    "_fallback_decimal_places",
    "_display_decimal",
    "_normalize_answer_number_formatting",
    "_fallback_period",
    "_fallback_period_value",
    "_fallback_decimal",
)  # noqa: E501
