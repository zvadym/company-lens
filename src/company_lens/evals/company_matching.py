from __future__ import annotations

from company_lens.evals.golden import ExpectedCompany
from company_lens.evals.models import ObservedCompany


def find_observed_company(
    expected: ExpectedCompany,
    observed_companies: tuple[ObservedCompany, ...],
) -> tuple[int, ObservedCompany | None]:
    expected_keys = expected_company_keys(expected)
    candidates = [
        (index, observed)
        for index, observed in enumerate(observed_companies)
        if expected_keys & observed_company_keys(observed)
    ]
    for index, observed in candidates:
        if observed.status == expected.status and observed.source == expected.source:
            return index, observed
    return candidates[0] if candidates else (-1, None)


def expected_company_keys(company: ExpectedCompany) -> set[str]:
    keys = {normalize_company_key(company.mention)}
    if company.ticker:
        keys.add(normalize_company_key(company.ticker))
    return keys


def observed_company_keys(company: ObservedCompany) -> set[str]:
    keys = {normalize_company_key(company.mention)}
    if company.ticker:
        keys.add(normalize_company_key(company.ticker))
    return keys


def observed_company_display_key(company: ObservedCompany) -> str:
    return normalize_company_key(company.ticker or company.mention)


def normalize_company_key(value: str) -> str:
    return " ".join(value.split()).casefold()


__all__ = (
    "expected_company_keys",
    "find_observed_company",
    "normalize_company_key",
    "observed_company_display_key",
    "observed_company_keys",
)
