"""Find prose numerals lacking a matching explicit claim.

Owns: Numeric syntax, canonical unit conversion, and inline row references.
Does not own: Semantic interpretation of prose or truth of claims.
"""

import re
from decimal import Decimal

from acquirer_engine.validation.schema import AcquirerRationale, Claim, prose_sections


def _matches(number: str, unit: str, claim: Claim, tolerance: float) -> bool:
    value = Decimal(number.replace(",", "").replace("−", "-"))
    expected = Decimal(str(claim.value))
    normalized = unit.casefold()
    scale = Decimal(1)
    if normalized in {"b", "bn", "billion", "m", "mm", "million", "k", "thousand"}:
        multiplier = {"b": 1000, "bn": 1000, "billion": 1000, "k": 0.001, "thousand": 0.001}.get(
            normalized, 1
        )
        if not claim.metric.endswith("_mm"):
            return False
        scale = Decimal(str(multiplier))
    elif normalized in {"%", "percent"}:
        if claim.metric.endswith("_rate"):
            scale = Decimal("0.01")
        elif not claim.metric.endswith("_pct"):
            return False
    elif normalized == "x" and "multiple" not in claim.metric:
        return False
    difference = abs(value * scale - expected)
    if claim.metric.endswith("_count") or claim.metric in {"deal_year", "relevant_deals"}:
        return difference == 0
    # Bound rounding by both written precision and the canonical-unit policy.
    half_unit = Decimal(10) ** int(value.as_tuple().exponent) * scale / 2
    return difference <= min(Decimal(str(tolerance)), half_unit)


def scan_numbers(page: AcquirerRationale, evidence_ids: set[str], tolerance: float) -> list[str]:
    """Check numerals including years, ranges, percentages, and multiples.

    Args:
        page: Parsed rationale with claims in canonical metric units.
        evidence_ids: IDs actually present in the supplied context.
        tolerance: Maximum rounding difference in the claim's canonical units.
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
        text = re.sub(r"(?<=\d)([%xX]?)\s*[-–]\s*(?=\d)", r"\1 to ", text)
        for match in pattern.finditer(text):
            number, unit = match.group("number"), match.group("unit") or ""
            if not any(_matches(number, unit, claim, tolerance) for claim in page.claims):
                errors.append(f"{path}: stray number {number}{unit}")
    return errors
