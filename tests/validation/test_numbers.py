"""Exercise numeric notation independently of numeric truth.

Owns: Leading decimals and explicit unit correctness in prose.
Does not own: A semantic understanding of which subject owns a claim.
"""

import pytest

from acquirer_engine.errors import ValidationFailure
from acquirer_engine.settings import Settings
from acquirer_engine.validation.claims import validate_rationale
from tests.fixtures.rationale import evidence_context, rationale_payload


@pytest.mark.parametrize("text", ["Margin is .999%.", "Margin is −.999%.", "Capacity is $200B."])
def test_numeric_notation_cannot_hide_an_unclaimed_value(settings: Settings, text: str) -> None:
    raw = rationale_payload()
    raw["strategic_fit_thesis"] = text
    with pytest.raises(ValidationFailure, match="stray number"):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


@pytest.mark.parametrize(
    "text", ["Capacity is $0.2B.", "Capacity is $200 million.", "EV was 2e2 million."]
)
def test_currency_units_are_normalized_to_canonical_millions(settings: Settings, text: str) -> None:
    raw = rationale_payload()
    raw["strategic_fit_thesis"] = text
    validate_rationale(raw, evidence_context(settings), settings.evidence.validation)
