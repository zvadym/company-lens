from __future__ import annotations

from pathlib import Path

import yaml

from data_checks.models import CompanyConfig, FredSeriesConfig, PdfConfig


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
REPORTS_DIR = ROOT / "reports"


def load_companies(path: Path = CONFIG_DIR / "companies.yaml") -> list[CompanyConfig]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    companies: list[CompanyConfig] = []
    for item in raw.get("companies", []):
        pdfs = [
            PdfConfig(
                label=str(pdf["label"]),
                type=str(pdf["type"]),
                url=str(pdf["url"]),
            )
            for pdf in item.get("pdfs", [])
        ]
        companies.append(
            CompanyConfig(
                name=str(item["name"]),
                ticker=str(item["ticker"]).upper(),
                cik=str(item["cik"]) if item.get("cik") is not None else None,
                pdfs=pdfs,
            )
        )
    return companies


def load_fred_series(path: Path = CONFIG_DIR / "fred_series.yaml") -> list[FredSeriesConfig]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    return [
        FredSeriesConfig(id=str(item["id"]), name=str(item["name"]))
        for item in raw.get("series", [])
    ]
