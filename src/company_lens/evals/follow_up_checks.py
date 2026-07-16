from __future__ import annotations

from company_lens.evals.company_matching import (
    expected_company_keys,
    normalize_company_key,
    observed_company_keys,
)
from company_lens.evals.golden import ExpectedCompany, GoldenDatasetCase
from company_lens.evals.models import ObservedCaseResult, ObservedCompany


def check_follow_up(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    follow_up = case.expected.follow_up
    if follow_up is None:
        return True

    passed = True
    company_keys = _follow_up_company_keys(case, observed.companies)
    reused = sorted(
        {normalize_company_key(item) for item in follow_up.prohibited_companies} & company_keys
    )
    if reused:
        failures.append(f"reused prohibited follow-up companies: {', '.join(reused)}")
        passed = False
    resolved_terms = sorted(
        {normalize_company_key(item) for item in follow_up.must_not_resolve_terms_as_company}
        & company_keys
    )
    if resolved_terms:
        failures.append(f"resolved non-company terms as companies: {', '.join(resolved_terms)}")
        passed = False
    missing_added = sorted(
        {normalize_company_key(item) for item in follow_up.add_companies} - company_keys
    )
    if missing_added:
        failures.append(f"missing added follow-up companies: {', '.join(missing_added)}")
        passed = False
    if follow_up.replace_companies is not None:
        replaced_from = {normalize_company_key(item) for item in follow_up.replace_companies.from_}
        replaced_to = {normalize_company_key(item) for item in follow_up.replace_companies.to}
        still_present = sorted(replaced_from & company_keys)
        missing_replacements = sorted(replaced_to - company_keys)
        if still_present:
            failures.append(f"kept replaced follow-up companies: {', '.join(still_present)}")
            passed = False
        if missing_replacements:
            failures.append(
                f"missing replacement follow-up companies: {', '.join(missing_replacements)}"
            )
            passed = False
    missing = sorted(
        expected.mention
        for expected in case.expected.companies
        if not _matches_expected_company(expected, observed.companies)
    )
    if missing:
        failures.append(f"missing expected follow-up targets: {', '.join(missing)}")
        passed = False
    return passed


def _follow_up_company_keys(
    case: GoldenDatasetCase,
    observed_companies: tuple[ObservedCompany, ...],
) -> set[str]:
    keys = {key for company in observed_companies for key in observed_company_keys(company)}
    for expected in case.expected.companies:
        expected_keys = expected_company_keys(expected)
        if any(expected_keys & observed_company_keys(company) for company in observed_companies):
            # Follow-up rules use company names, while observations may expose only tickers.
            keys.update(expected_keys)
    return keys


def _matches_expected_company(
    expected: ExpectedCompany,
    observed_companies: tuple[ObservedCompany, ...],
) -> bool:
    expected_keys = expected_company_keys(expected)
    return any(expected_keys & observed_company_keys(company) for company in observed_companies)


__all__ = ("check_follow_up",)
