from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAPPING_PATH = Path("config/financial_metric_mappings.v1.yaml")


@dataclass(frozen=True)
class MetricMapping:
    version: str
    concepts: dict[tuple[str, str], str]
    company_concepts: dict[tuple[str, str, str], str]

    def resolve(self, *, cik: str, taxonomy: str, concept: str) -> str | None:
        normalized_cik = cik.zfill(10)
        return self.company_concepts.get((normalized_cik, taxonomy, concept)) or self.concepts.get(
            (taxonomy, concept)
        )


def load_metric_mapping(path: Path = DEFAULT_MAPPING_PATH) -> MetricMapping:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Metric mapping must be a YAML object: {path}")
    version = _required_string(payload, "version")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("Metric mapping must define at least one metric.")

    concepts: dict[tuple[str, str], str] = {}
    for metric, taxonomy_map in metrics.items():
        for taxonomy, concept in _taxonomy_concepts(str(metric), taxonomy_map):
            key = (taxonomy, concept)
            _validate_unique(concepts.get(key), key, str(metric))
            concepts[key] = str(metric)

    company_concepts: dict[tuple[str, str, str], str] = {}
    overrides = payload.get("company_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("company_overrides must be an object.")
    for cik, company_metrics in overrides.items():
        if not isinstance(company_metrics, dict):
            raise ValueError(f"Company override {cik} must be an object.")
        for metric, taxonomy_map in company_metrics.items():
            for taxonomy, concept in _taxonomy_concepts(str(metric), taxonomy_map):
                company_key = (str(cik).zfill(10), taxonomy, concept)
                _validate_unique(company_concepts.get(company_key), company_key, str(metric))
                company_concepts[company_key] = str(metric)

    return MetricMapping(
        version=version,
        concepts=concepts,
        company_concepts=company_concepts,
    )


def _taxonomy_concepts(metric: str, taxonomy_map: Any) -> list[tuple[str, str]]:
    if not isinstance(taxonomy_map, dict):
        raise ValueError(f"Metric {metric} must map taxonomies to concept lists.")
    entries: list[tuple[str, str]] = []
    for taxonomy, raw_concepts in taxonomy_map.items():
        if not isinstance(raw_concepts, list) or not raw_concepts:
            raise ValueError(f"Metric {metric}/{taxonomy} must have a non-empty concept list.")
        for concept in raw_concepts:
            entries.append((str(taxonomy), str(concept)))
    return entries


def _validate_unique(
    previous: str | None,
    key: tuple[str, ...],
    metric: str,
) -> None:
    if previous is not None and previous != metric:
        raise ValueError(f"Concept {'/'.join(key)} maps to both {previous} and {metric}.")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Metric mapping field {key} must be a non-empty string.")
    return value.strip()
