"""Reject the observed sector-margin inversion without claiming semantic coverage.

Owns: Explicit target-versus-sector median margin assertions.
Does not own: Open-ended interpretation or banker judgment.
"""

import pytest

from acquirer_engine.errors import ValidationFailure
from acquirer_engine.evidence.ids import stat_id
from acquirer_engine.evidence.pack import Statistic
from acquirer_engine.settings import Settings
from acquirer_engine.validation.claims import validate_rationale
from tests.fixtures.rationale import evidence_context, rationale_payload


@pytest.mark.parametrize(
    "text",
    [
        "This target is a private, regional asset with a below-sector-median margin profile.",
        "The target's EBITDA margin is below the Closed-sector median.",
    ],
)
def test_rejects_target_margin_below_lower_sector_median(settings: Settings, text: str) -> None:
    context = evidence_context(settings)
    stat = Statistic(
        evidence_id=stat_id("median_ebitda_margin_pct", "closed-sector-Services"),
        metric="median_ebitda_margin_pct",
        value=15,
    )
    context = context.model_copy(update={"statistics": (stat,)})
    payload = rationale_payload() | {"strategic_fit_thesis": text}
    with pytest.raises(ValidationFailure, match="sector.*margin comparison"):
        validate_rationale(payload, context, settings.evidence.validation)


def test_rejects_sector_margin_comparison_without_retrieved_benchmark(settings: Settings) -> None:
    payload = rationale_payload() | {
        "strategic_fit_thesis": "The target has a below-sector-median margin profile."
    }
    with pytest.raises(ValidationFailure, match="retrieved.*benchmark"):
        validate_rationale(payload, evidence_context(settings), settings.evidence.validation)


@pytest.mark.parametrize("median, direction", [(15, "above"), (25, "below")])
def test_accepts_supported_explicit_sector_margin_comparison(
    settings: Settings, median: float, direction: str
) -> None:
    context = evidence_context(settings)
    stat = Statistic(
        evidence_id=stat_id("median_ebitda_margin_pct", "closed-sector-Services"),
        metric="median_ebitda_margin_pct",
        value=median,
    )
    context = context.model_copy(update={"statistics": (stat,)})
    payload = rationale_payload() | {
        "strategic_fit_thesis": f"The target's margin is {direction} the Closed-sector median."
    }
    assert validate_rationale(payload, context, settings.evidence.validation)
