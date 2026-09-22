"""Keep retrieved ownership and malformed prose at the validation boundary.

Owns: Own-buyer comp provenance and unsupported numeric syntax failures.
Does not own: Retrieval policy or generation quality.
"""

import pytest

from acquirer_engine.errors import ValidationFailure
from acquirer_engine.llm.tools import EvidenceTools, NumericBand, ToolState
from acquirer_engine.settings import Settings
from acquirer_engine.validation.claims import validate_rationale
from tests.fixtures.rationale import evidence_context, rationale_payload


@pytest.mark.parametrize("own_buyer", [True, False])
def test_retrieved_comp_can_be_a_precedent_only_for_its_own_buyer(
    settings: Settings, own_buyer: bool
) -> None:
    context = evidence_context(settings)
    row = context.comparable_deals[0]
    if own_buyer:
        row = row.model_copy(update={"acquirer": context.core.ranking.acquirer})
    tools = EvidenceTools((*context.core.deals, row), settings.analyst)
    state = ToolState(context.core, settings.analyst.max_tool_rounds)
    state.record(1, tools.comparable_deals("Services", NumericBand(low=100, high=400), None, None))
    raw = rationale_payload()
    raw["precedent_activity"] = [
        {"transaction_id": row.transaction_id, "description": "A retrieved precedent."}
    ]
    if own_buyer:
        page = validate_rationale(raw, state.context(), settings.evidence.validation)
        assert page.precedent_activity[0].transaction_id == row.transaction_id
    else:
        with pytest.raises(ValidationFailure, match="unknown own-history evidence"):
            validate_rationale(raw, state.context(), settings.evidence.validation)


@pytest.mark.parametrize("number", ["1e1000000", "1e99999999999999999999"])
def test_unsupported_numeric_magnitude_is_a_validation_failure(
    settings: Settings, number: str
) -> None:
    raw = rationale_payload()
    raw["strategic_fit_thesis"] = f"Recorded capacity is {number}."
    with pytest.raises(ValidationFailure, match="stray number"):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)
