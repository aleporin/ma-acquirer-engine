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


def test_prose_can_round_a_precise_verified_multiple(settings: Settings) -> None:
    raw = rationale_payload()
    claims = raw["claims"]
    assert isinstance(claims, list)
    claims[2]["value"] = 13.64
    validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


@pytest.mark.parametrize("text", ["The comp paid 13.61x.", "The comp paid 13.7x."])
def test_rounding_does_not_accept_a_different_displayed_value(
    settings: Settings, text: str
) -> None:
    raw = rationale_payload()
    claims = raw["claims"]
    assert isinstance(claims, list)
    claims[2]["value"] = 13.64
    raw["strategic_fit_thesis"] = text
    with pytest.raises(ValidationFailure, match="stray number"):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


@pytest.mark.parametrize(
    ("metric", "value", "text", "accepted"),
    [
        ("ebitda_margin_pct", 16.533333333, "Margin is 16.5%.", True),
        ("completion_rate", 0.916666667, "Completion is 91.7%.", True),
        ("completion_rate", 0.916666667, "Completion is 90.0%.", False),
        ("profile_fit.raw", 0.834677419, "Profile fit is 0.83.", True),
        ("profile_fit.raw", 0.834677419, "Profile fit is 0.82.", False),
        ("deal_count", 4, "History shows 3.99 deals.", False),
        ("deal_year", 2020, "History ends in 2019.99.", False),
        ("ebitda_margin_pct", 19.9, "Margin ranges from 19.9%-20%.", True),
    ],
)
def test_rounding_preserves_units_precision_and_discrete_facts(
    settings: Settings, metric: str, value: float, text: str, accepted: bool
) -> None:
    from acquirer_engine.evidence.pack import Statistic

    raw = rationale_payload()
    raw["strategic_fit_thesis"] = text
    claims = raw["claims"]
    assert isinstance(claims, list)
    stat = Statistic(evidence_id="stat:test:scope", metric=metric, value=value)
    context = evidence_context(settings).model_copy(update={"statistics": (stat,)})
    claims.extend(
        [
            stat.model_dump(),
            {"value": 20, "metric": "ebitda_margin_pct", "evidence_id": "MA-2020-0001"},
        ]
    )
    if accepted:
        validate_rationale(raw, context, settings.evidence.validation)
    else:
        with pytest.raises(ValidationFailure, match="stray number"):
            validate_rationale(raw, context, settings.evidence.validation)
