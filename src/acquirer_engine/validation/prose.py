"""Check rationale wording against configured phrases and narrow evidence rules.

Owns: Boilerplate, explicit margin direction, and partial-history theme scope.
Does not own: Numeric matching or general semantic verification.
"""

import re

from acquirer_engine.evidence.pack import EvidenceContext, stat_id
from acquirer_engine.validation.schema import AcquirerRationale, prose_sections


def sector_margin_errors(page: AcquirerRationale, context: EvidenceContext) -> list[str]:
    """Compare explicit above/below sector-median assertions to retrieved facts.

    Args:
        page: Parsed prose, including the private reasoning summary.
        context: Actual target assumptions and retrieved sector statistics.
    Returns:
        Repairable errors for missing benchmarks or contradictory directions.
        Unrecognized prose remains outside this narrow check's coverage.
    """
    key = stat_id("median_ebitda_margin_pct", f"closed-sector-{context.core.target.sector}")
    benchmark = next((s for s in context.statistics if s.evidence_id == key), None)
    errors = []
    for path, prose in prose_sections(page).items():
        for sentence in re.split(r"[.!?;]\s+", prose.lower().replace("-", " ")):
            direction = _explicit_direction(sentence)
            if direction is None:
                continue
            prefix = f"{path}: sector median margin comparison"
            if benchmark is None:
                errors.append(f"{prefix} requires a retrieved Closed-sector benchmark")
                continue
            difference = context.core.target.ebitda_margin_pct - benchmark.value
            expected = "above" if difference > 0 else "below" if difference < 0 else "equal"
            if direction != expected:
                errors.append(
                    f"{prefix} contradicts evidence: target margin is {expected} the median"
                )
    return errors


def _explicit_direction(sentence: str) -> str | None:
    benchmark = r"(?:the\s+)?(?:closed\s+)?sector\s+median"
    patterns = (
        rf"\btarget['’]?s?\s+(?:ebitda\s+)?margin(?:\s+profile)?\s+"
        rf"(?:is|sits|lies)\s+(above|below)\s+{benchmark}",
        rf"\btarget\b[^.!?;]*?\ba\s+(above|below)\s+{benchmark}\s+margin",
        rf"\btarget\b[^.!?;]*?\ban\s+(above|below)\s+{benchmark}\s+margin",
    )
    for pattern in patterns:
        match = re.search(pattern, sentence)
        if match:
            return match.group(1)
    return None


def theme_scope_errors(page: AcquirerRationale, context: EvidenceContext) -> list[str]:
    """Require complete own-history coverage for recognized exclusive theme prose.

    Args:
        page: Parsed prose, including the private reasoning summary.
        context: Actual core and retrieved rows available to this draft.
    Returns:
        Repairable errors requesting positive examples instead of exclusivity.
        Complete coverage lifts this scope restriction, not all semantic checks.
    """
    own_ids = {
        row.transaction_id
        for row in (*context.core.deals, *context.retrieved_deals, *context.comparable_deals)
        if row.acquirer == context.core.ranking.acquirer
    }
    if len(own_ids) == context.core.total_rows:
        return []
    themes = [tag.casefold().replace("-", " ") for tag in context.core.target.tags]
    errors = []
    for path, prose in prose_sections(page).items():
        for sentence in re.split(r"[.!?;]\s+", prose.casefold().replace("-", " ")):
            if any(theme in sentence for theme in themes) and re.search(
                r"\bonly\s+(?:through|in|on)\b", sentence
            ):
                errors.append(
                    f"{path}: exclusive theme assertion requires complete buyer history; "
                    "describe an observed positive example without claiming exclusivity"
                )
    return errors


def banned_phrases(page: AcquirerRationale, phrases: tuple[str, ...]) -> list[str]:
    """Return specific field paths for configured boilerplate.

    Args:
        page: Parsed rationale.
        phrases: Forbidden phrases from configuration.
    Returns:
        Actionable validation errors.
    """
    errors = []
    for path, text in prose_sections(page).items():
        normalized = " ".join(text.casefold().split())
        for phrase in phrases:
            if " ".join(phrase.casefold().split()) in normalized:
                errors.append(f"{path}: banned phrase '{phrase}'")
    return errors
