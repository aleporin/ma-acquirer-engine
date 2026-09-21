"""Find prose numerals lacking a matching explicit claim.

Owns: Numeric syntax, canonical unit conversion, and inline row references.
Does not own: Semantic interpretation of prose or truth of claims.
"""

import re
from decimal import Decimal

from acquirer_engine.validation.schema import AcquirerRationale, Claim, prose_sections


def _matches(number: str, unit: str, claim: Claim) -> bool:
    value = Decimal(number.replace(",", "").replace("−", "-"))
    expected = Decimal(str(claim.value))
    normalized = unit.casefold()
    if normalized in {"b", "bn", "billion", "m", "mm", "million", "k", "thousand"}:
        multiplier = {"b": 1000, "bn": 1000, "billion": 1000, "k": 0.001, "thousand": 0.001}.get(
            normalized, 1
        )
        return claim.metric.endswith("_mm") and value * Decimal(str(multiplier)) == expected
    if normalized in {"%", "percent"}:
        if claim.metric.endswith("_rate"):
            return value / 100 == expected
        return claim.metric.endswith("_pct") and value == expected
    if normalized == "x":
        return "multiple" in claim.metric and value == expected
    return value == expected


def scan_numbers(page: AcquirerRationale, evidence_ids: set[str]) -> list[str]:
    """Check numerals including years, ranges, percentages, and multiples.

    Args:
        page: Parsed rationale with claims in canonical metric units.
        evidence_ids: IDs actually present in the supplied context.
    Returns:
        Stray-number and unresolved inline-reference errors with field paths.
    """
    errors = []
    pattern = re.compile(
        r"(?<![\w.])(?P<number>[+−-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)"
        r"\s*(?P<unit>percent\b|billion\b|million\b|thousand\b|bn\b|mm\b|[BMKXbmkx%](?!\w))?"
    )
    for path, text in prose_sections(page).items():
        for reference in re.findall(r"MA-\d{4}-\d{4}", text):
            if reference not in evidence_ids:
                errors.append(f"{path}: unknown evidence {reference}")
        text = re.sub(r"MA-\d{4}-\d{4}", "", text)
        # In an unsigned range the dash separates endpoints, not a negative sign.
        text = re.sub(r"(?<=\d)[-–](?=\d)", " to ", text)
        for match in pattern.finditer(text):
            number, unit = match.group("number"), match.group("unit") or ""
            if not any(_matches(number, unit, claim) for claim in page.claims):
                errors.append(f"{path}: stray number {number}{unit}")
    return errors
