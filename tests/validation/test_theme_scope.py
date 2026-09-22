"""Bound exclusive theme assertions to complete buyer-history coverage.

Owns: Regression coverage for partial-history exclusivity and safe alternatives.
Does not own: General semantic truth or exhaustive paraphrase detection.
"""

import pytest

from acquirer_engine.errors import ValidationFailure
from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.settings import Settings
from acquirer_engine.validation.claims import validate_rationale
from tests.fixtures.rationale import evidence_context, rationale_payload


def theme_context(settings: Settings, *, complete: bool = False) -> EvidenceContext:
    context = evidence_context(settings)
    rows = tuple(
        row.model_copy(update={"strategic_rationale_tags": "Margin Improvement"})
        for row in context.core.deals
    )
    core = context.core.model_copy(
        update={
            "target": context.core.target.model_copy(update={"tags": ("Margin Improvement",)}),
            "deals": rows if complete else rows[:2],
            "truncated": not complete,
        }
    )
    return context.model_copy(update={"core": core})


@pytest.mark.parametrize(
    "text",
    [
        "Margin Improvement is evidenced only through an adjacent transaction.",
        "The buyer's margin-improvement theme appears only on adjacent-sector deals.",
        "The buyer has Margin Improvement only in Services.",
    ],
)
def test_rejects_exclusive_theme_claim_with_partial_history(settings: Settings, text: str) -> None:
    payload = rationale_payload() | {"strategic_fit_thesis": text}
    with pytest.raises(ValidationFailure, match="exclusive theme.*complete buyer history"):
        validate_rationale(payload, theme_context(settings), settings.evidence.validation)


@pytest.mark.parametrize(
    "text",
    [
        "An adjacent transaction carries a Margin Improvement theme.",
        "Margin improvement is plausible only if diligence supports the operating plan.",
    ],
)
def test_accepts_positive_examples_and_conditional_judgment(settings: Settings, text: str) -> None:
    payload = rationale_payload() | {"strategic_fit_thesis": text}
    assert validate_rationale(payload, theme_context(settings), settings.evidence.validation)


def test_retrieval_can_complete_buyer_history_without_counting_duplicates(
    settings: Settings,
) -> None:
    partial = theme_context(settings)
    full = theme_context(settings, complete=True)
    payload = rationale_payload() | {
        "reasoning": "The buyer has Margin Improvement only in Services."
    }
    duplicate = partial.model_copy(update={"retrieved_deals": partial.core.deals})
    with pytest.raises(ValidationFailure, match="exclusive theme"):
        validate_rationale(payload, duplicate, settings.evidence.validation)
    covered = partial.model_copy(update={"retrieved_deals": full.core.deals})
    assert validate_rationale(payload, covered, settings.evidence.validation)
    assert validate_rationale(payload, full, settings.evidence.validation)
