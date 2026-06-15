from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Status = Literal["passed", "warning", "failed", "skipped"]


@dataclass(frozen=True)
class PdfConfig:
    label: str
    type: str
    url: str


@dataclass(frozen=True)
class CompanyConfig:
    name: str
    ticker: str
    cik: str | None = None
    pdfs: list[PdfConfig] = field(default_factory=list)


@dataclass(frozen=True)
class FredSeriesConfig:
    id: str
    name: str


@dataclass
class CheckResult:
    source: str
    check: str
    status: Status
    message: str
    company: str | None = None
    ticker: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "source": self.source,
            "check": self.check,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }
        if self.company:
            data["company"] = self.company
        if self.ticker:
            data["ticker"] = self.ticker
        return data
