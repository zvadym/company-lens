from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .shared import *  # noqa: F403
from .builders import _financial_observation
from .fakes_financial import AnnualSeriesFinancialTools
from .fakes_tools import AnnualMacroTools, FakeResearchTools

# ruff: noqa: F405

class AnnualFinancialAndMacroTools(AnnualMacroTools, AnnualSeriesFinancialTools):
    pass


class AnnualFinancialAndMonthlyMacroTools(AnnualSeriesFinancialTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        return FredSeriesResult(
            query=request,
            series=(),
            observations=tuple(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(year, 12, 1),
                    realtime_start=date(year, 12, 1),
                    realtime_end=date(year, 12, 1),
                    value=value,
                    raw_value=str(value),
                    is_missing=False,
                    unit="percent",
                    frequency="Monthly",
                    source_url=f"https://fred.example/FEDFUNDS/{year}",
                )
                for year, value in (
                    (2023, Decimal("5.25")),
                    (2024, Decimal("5.00")),
                    (2025, Decimal("4.50")),
                )
            ),
        )


class FlakyFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        if self.calls["financial"] == 1:
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.TOOL,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="temporary_tool_failure",
                    message="Temporary tool failure.",
                )
            )
        self.calls["financial"] -= 1
        return super().query_financial_facts(request)


class PunctuatedCompanyFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        return FinancialFactQueryResult(
            query=request,
            observations=(
                _financial_observation(date(2025, 12, 31), Decimal("125")).model_copy(
                    update={"company_name": "Elastic N.V.", "ticker": "ESTC"}
                ),
            ),
            available_units=("USD",),
        )


class BrokenMacroTools(FakeResearchTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        raise ResearchToolError(
            AgentError(
                category=AgentErrorCategory.TOOL,
                severity=AgentErrorSeverity.TERMINAL,
                code="macro_unavailable",
                message="Macro data is unavailable.",
            )
        )


class MonthlyMacroTools(FakeResearchTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        return FredSeriesResult(
            query=request,
            series=(),
            observations=tuple(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(2024, month, 1),
                    realtime_start=date(2024, month, 1),
                    realtime_end=date(2024, month, 1),
                    value=Decimal(month),
                    raw_value=str(month),
                    is_missing=False,
                    unit="percent",
                    frequency="Monthly",
                    source_url="https://fred.example/FEDFUNDS",
                )
                for month in range(1, 13)
            ),
        )

__all__ = ('AnnualFinancialAndMacroTools', 'AnnualFinancialAndMonthlyMacroTools', 'FlakyFinancialTools', 'PunctuatedCompanyFinancialTools', 'BrokenMacroTools', 'MonthlyMacroTools')  # noqa: E501
