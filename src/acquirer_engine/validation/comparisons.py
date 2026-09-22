"""Check explicit target-to-sector median margin comparisons.

Owns: A narrow guard against the observed margin-direction inversion.
Does not own: General semantic verification, peer definitions, or banker judgment.
"""

import re

from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.evidence.ids import stat_id
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
