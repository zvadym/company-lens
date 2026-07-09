from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from inspect import Parameter, signature

from company_lens.evidence.claims import extract_claims
from company_lens.evidence.registry import EvidenceRegistry
from company_lens.evidence.schemas import (
    AnswerValidation,
    ClaimRecord,
    ClaimValidation,
    EvidenceEnvelope,
    EvidenceKind,
    SemanticSupportResult,
    SemanticSupportStatus,
    ValidationIssue,
)

SemanticSupportJudge = Callable[..., SemanticSupportResult]
APPEALABLE_DETERMINISTIC_ISSUES = frozenset(
    {
        "unsupported_number",
        "wrong_period",
        "wrong_unit",
    }
)

YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
NUMBER_PATTERN = re.compile(r"(?<![\w-])[-+]?\d[\d,]*(?:\.\d+)?")
SCALED_NUMBER_PATTERN = re.compile(
    r"(?<![\w-])(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<scale>thousand|million|billion|trillion|k|mn|bn))?",
    re.IGNORECASE,
)
NUMBER_SCALES = {
    "k": Decimal("1000"),
    "thousand": Decimal("1000"),
    "mn": Decimal("1000000"),
    "million": Decimal("1000000"),
    "bn": Decimal("1000000000"),
    "billion": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
}
CAUSATION_PATTERN = re.compile(
    r"\b(?:cause[ds]?|causing|led to|resulted in|drove|because of|due to)\b", re.IGNORECASE
)
CORRELATION_QUALIFIER_PATTERN = re.compile(
    r"\b(?:correlat(?:ion|ed)|associat(?:ion|ed)|not causation|does not imply causation)\b",
    re.IGNORECASE,
)
FILING_FORM_PATTERN = re.compile(
    r"\b(?:10-K|10-Q|8-K|20-F|40-F|6-K|S-1)(?:/A)?\b",
    re.IGNORECASE,
)
SEC_SECTION_LABEL_PATTERN = re.compile(
    r"\b(?:Item\s+(?:\d{1,2}[A-Z]?|[IVX]+)|Part\s+(?:[IVX]+|\d+))\.",
    re.IGNORECASE,
)


class AnswerValidator:
    def __init__(
        self,
        registry: EvidenceRegistry,
        *,
        semantic_judge: SemanticSupportJudge | None = None,
        semantic_issue_appeal_judge: SemanticSupportJudge | None = None,
    ) -> None:
        self._registry = registry
        self._semantic_judge = semantic_judge
        self._semantic_issue_appeal_judge = semantic_issue_appeal_judge or semantic_judge

    def validate(self, answer: str, *, citations_required: bool = True) -> AnswerValidation:
        claims = extract_claims(answer)
        claim_validations = tuple(
            self._validate_claim(claim, citations_required=citations_required) for claim in claims
        )
        cited = tuple(
            dict.fromkeys(evidence_id for claim in claims for evidence_id in claim.evidence_ids)
        )
        unknown = tuple(evidence_id for evidence_id in cited if evidence_id not in self._registry)
        issues = tuple(issue for claim in claim_validations for issue in claim.issues)
        reason_codes = tuple(dict.fromkeys(issue.code for issue in issues))
        return AnswerValidation(
            valid=not issues,
            claims=claim_validations,
            cited_evidence_ids=tuple(
                evidence_id for evidence_id in cited if evidence_id in self._registry
            ),
            unknown_evidence_ids=unknown,
            reason_codes=reason_codes,
            issues=issues,
        )

    def _validate_claim(self, claim: ClaimRecord, *, citations_required: bool) -> ClaimValidation:
        issues: list[ValidationIssue] = []
        semantic_support: SemanticSupportResult | None = None
        known_evidence = tuple(
            evidence
            for evidence_id in claim.evidence_ids
            if (evidence := self._registry.get(evidence_id)) is not None
        )
        for evidence_id in claim.evidence_ids:
            if evidence_id not in self._registry:
                issues.append(
                    self._issue(
                        "unknown_citations",
                        "The citation was not present in the assembled context.",
                        claim,
                        evidence_id,
                    )
                )
        if claim.material and citations_required and not claim.evidence_ids:
            issues.append(
                self._issue(
                    "unsupported_claim",
                    "A material claim has no supporting citation.",
                    claim,
                )
            )
        if known_evidence:
            issues.extend(self._validate_metadata(claim, known_evidence))
            issues.extend(self._validate_lineage(claim, known_evidence))
            semantic_support_ran = False
            if issues and self._semantic_issue_appeal_judge is not None:
                semantic_support = _semantic_issue_appeal(
                    self._semantic_issue_appeal_judge,
                    claim,
                    known_evidence,
                    tuple(issues),
                )
                semantic_support_ran = semantic_support is not None
                if semantic_support is not None:
                    issues = _issues_after_semantic_appeal(issues, semantic_support)
            if not issues and self._semantic_judge is not None and not semantic_support_ran:
                semantic_support = _call_semantic_judge(
                    self._semantic_judge,
                    claim,
                    known_evidence,
                )
                if semantic_support.status is SemanticSupportStatus.UNSUPPORTED:
                    issues.append(
                        self._issue(
                            "semantic_support_failed",
                            "The cited evidence does not semantically support the claim.",
                            claim,
                        )
                    )
        return ClaimValidation(
            claim_id=claim.claim_id,
            supported=not issues and (bool(known_evidence) or not claim.material),
            evidence_ids=claim.evidence_ids,
            issues=tuple(issues),
            semantic_support=semantic_support,
        )

    def _validate_metadata(
        self, claim: ClaimRecord, evidence: tuple[EvidenceEnvelope, ...]
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        claim_lower = claim.text.casefold()
        all_companies = {
            item.metadata.company_name.casefold(): item.metadata.company_name
            for item in self._registry.records()
            if item.metadata.company_name
        }
        mentioned_companies = {
            canonical
            for normalized, canonical in all_companies.items()
            if normalized in claim_lower
        }
        cited_companies = {
            item.metadata.company_name
            for item in evidence
            if item.metadata.company_name is not None
        }
        if mentioned_companies and cited_companies.isdisjoint(mentioned_companies):
            issues.append(
                self._issue(
                    "wrong_company",
                    "The cited evidence belongs to a different company than the claim.",
                    claim,
                )
            )

        claim_years = {int(value) for value in YEAR_PATTERN.findall(claim.text)}
        evidence_years = {
            year for item in evidence for year in _evidence_years(item) if year is not None
        }
        if claim_years and evidence_years and claim_years.isdisjoint(evidence_years):
            issues.append(
                self._issue(
                    "wrong_period",
                    "The cited evidence does not match the period stated in the claim.",
                    claim,
                )
            )

        known_units = {
            item.metadata.unit.casefold() for item in self._registry.records() if item.metadata.unit
        }
        claim_units = {unit for unit in known_units if _contains_token(claim_lower, unit)}
        if "%" in claim.text or "percent" in claim_lower:
            claim_units.add("percent")
        if "$" in claim.text:
            claim_units.add("usd")
        evidence_units = {item.metadata.unit.casefold() for item in evidence if item.metadata.unit}
        if claim_units and evidence_units and claim_units.isdisjoint(evidence_units):
            issues.append(
                self._issue(
                    "wrong_unit",
                    "The cited evidence does not match the unit stated in the claim.",
                    claim,
                )
            )

        unsupported_numbers = _unsupported_numbers(claim.text, evidence)
        if unsupported_numbers:
            issues.append(
                self._issue(
                    "unsupported_number",
                    "A numerical claim is not present in the cited evidence or calculation.",
                    claim,
                )
            )

        correlation_evidence = any(
            item.kind is EvidenceKind.CALCULATION and item.metadata.operation == "correlation"
            for item in evidence
        )
        if (
            correlation_evidence
            and CAUSATION_PATTERN.search(claim.text)
            and not CORRELATION_QUALIFIER_PATTERN.search(claim.text)
        ):
            issues.append(
                self._issue(
                    "correlation_as_causation",
                    "Correlation evidence cannot support an unqualified causal claim.",
                    claim,
                )
            )
        return issues

    def _validate_lineage(
        self, claim: ClaimRecord, evidence: tuple[EvidenceEnvelope, ...]
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for item in evidence:
            if item.kind is not EvidenceKind.CALCULATION:
                continue
            missing = tuple(ref for ref in item.lineage_refs if ref not in self._registry)
            if missing:
                issues.append(
                    self._issue(
                        "incomplete_calculation_lineage",
                        "The calculated value does not retain all input evidence records.",
                        claim,
                        item.evidence_id,
                    )
                )
        return issues

    @staticmethod
    def _issue(
        code: str,
        message: str,
        claim: ClaimRecord,
        evidence_id: str | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            message=message,
            claim_id=claim.claim_id,
            evidence_id=evidence_id,
        )


def _semantic_issue_appeal(
    judge: SemanticSupportJudge,
    claim: ClaimRecord,
    evidence: tuple[EvidenceEnvelope, ...],
    issues: tuple[ValidationIssue, ...],
) -> SemanticSupportResult | None:
    appealable = tuple(issue for issue in issues if issue.code in APPEALABLE_DETERMINISTIC_ISSUES)
    if not appealable:
        return None
    return _call_semantic_judge(judge, claim, evidence, appealable)


def _issues_after_semantic_appeal(
    issues: list[ValidationIssue],
    semantic_support: SemanticSupportResult,
) -> list[ValidationIssue]:
    if semantic_support.status is not SemanticSupportStatus.SUPPORTED:
        return issues
    # Older structured responses may omit per-issue codes; in appeal mode a
    # supported verdict means the supplied allowlisted issues were false positives.
    resolved = set(semantic_support.resolved_issue_codes) or {
        issue.code for issue in issues if issue.code in APPEALABLE_DETERMINISTIC_ISSUES
    }
    return [
        issue
        for issue in issues
        if issue.code not in APPEALABLE_DETERMINISTIC_ISSUES or issue.code not in resolved
    ]


def _call_semantic_judge(
    judge: SemanticSupportJudge,
    claim: ClaimRecord,
    evidence: tuple[EvidenceEnvelope, ...],
    issues: tuple[ValidationIssue, ...] = (),
) -> SemanticSupportResult:
    if issues and _semantic_judge_accepts_validation_issues(judge):
        return judge(claim, evidence, issues)
    return judge(claim, evidence)


def _semantic_judge_accepts_validation_issues(judge: SemanticSupportJudge) -> bool:
    try:
        call_signature = signature(judge)
    except (TypeError, ValueError):
        return True
    positional = (
        Parameter.POSITIONAL_ONLY,
        Parameter.POSITIONAL_OR_KEYWORD,
    )
    parameters = call_signature.parameters.values()
    if any(parameter.kind is Parameter.VAR_POSITIONAL for parameter in parameters):
        return True
    return (
        sum(parameter.kind in positional for parameter in call_signature.parameters.values()) >= 3
    )


def _evidence_years(evidence: EvidenceEnvelope) -> tuple[int | None, ...]:
    metadata = evidence.metadata
    return (
        metadata.fiscal_year,
        metadata.period_start.year if metadata.period_start else None,
        metadata.period_end.year if metadata.period_end else None,
        # Later filings can quote the annual-report year they refer to; that cited
        # text year should satisfy period checks even when filing metadata differs.
        *(int(value) for value in YEAR_PATTERN.findall(evidence.summary)),
    )


def _contains_token(text: str, token: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text))


def _unsupported_numbers(
    claim_text: str, evidence: tuple[EvidenceEnvelope, ...]
) -> tuple[Decimal, ...]:
    claim_years = {Decimal(value) for value in YEAR_PATTERN.findall(claim_text)}
    claim_numbers = _claim_numbers(claim_text, claim_years)
    if not claim_numbers:
        return ()
    supported: set[Decimal] = set()
    for item in evidence:
        if item.metadata.value is not None:
            supported.add(item.metadata.value)
        if item.metadata.formula is not None:
            supported.update(
                parsed
                for value in NUMBER_PATTERN.findall(item.metadata.formula)
                if (parsed := _decimal(value)) is not None
            )
        supported.update(
            parsed
            for value in NUMBER_PATTERN.findall(item.summary)
            if (parsed := _decimal(value)) is not None
        )
        # Document summaries can carry formatted values such as "302 million";
        # validate those in the same scale used for answer claims.
        supported.update(_scaled_numbers(item.summary))
        values = item.payload.get("values")
        inputs = item.payload.get("inputs")
        for collection in (values, inputs):
            if not isinstance(collection, list):
                continue
            for point in collection:
                if isinstance(point, dict) and (parsed := _decimal(point.get("value"))) is not None:
                    supported.add(parsed)
    return tuple(
        sorted(
            value
            for value, tolerance in claim_numbers
            if not any(abs(candidate - value) <= tolerance for candidate in supported)
        )
    )


def _claim_numbers(
    claim_text: str,
    claim_years: set[Decimal],
) -> tuple[tuple[Decimal, Decimal], ...]:
    result: list[tuple[Decimal, Decimal]] = []
    numeric_text = FILING_FORM_PATTERN.sub(" ", claim_text)
    numeric_text = SEC_SECTION_LABEL_PATTERN.sub(" ", numeric_text)
    for match in SCALED_NUMBER_PATTERN.finditer(numeric_text):
        raw = match.group("number")
        parsed = _decimal(raw)
        if parsed is None:
            continue
        scale_name = match.group("scale")
        if scale_name is None and parsed in claim_years:
            continue
        multiplier = (
            NUMBER_SCALES.get(scale_name.casefold(), Decimal(1)) if scale_name else Decimal(1)
        )
        normalized = parsed * multiplier
        decimal_places = len(raw.rsplit(".", 1)[1]) if "." in raw else 0
        displayed_quantum = Decimal(1).scaleb(-decimal_places) * multiplier
        result.append((normalized, displayed_quantum / 2))
    return tuple(result)


def _scaled_numbers(text: str) -> tuple[Decimal, ...]:
    result: list[Decimal] = []
    for match in SCALED_NUMBER_PATTERN.finditer(text):
        scale_name = match.group("scale")
        if scale_name is None:
            continue
        parsed = _decimal(match.group("number"))
        if parsed is None:
            continue
        multiplier = NUMBER_SCALES.get(scale_name.casefold())
        if multiplier is not None:
            result.append(parsed * multiplier)
    return tuple(result)


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None
