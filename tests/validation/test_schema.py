"""Specify the structured rationale boundary and configured size limits.

Owns: Required sections, risk provenance, and computed conviction enforcement.
Does not own: Numeric accuracy or output rendering.
"""

from copy import deepcopy
from typing import Any

import pytest

from acquirer_engine.errors import ValidationFailure
from acquirer_engine.settings import Settings
from acquirer_engine.validation.claims import validate_rationale
from acquirer_engine.validation.schema import AcquirerRationale, RiskFlag
from tests.fixtures.rationale import evidence_context, rationale_payload


def test_reasoning_is_first_in_the_output_schema() -> None:
    assert next(iter(AcquirerRationale.model_json_schema()["properties"])) == "reasoning"


def test_judgment_without_references_serializes_as_an_empty_list() -> None:
    risk = RiskFlag.model_validate(
        dict(category="fund_cycle", description="Fund timing is unknown.", basis="judgment")
    )
    assert risk.model_dump(mode="json")["evidence_ids"] == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("one_risk", "risk_flags"),
        ("unknown_risk", "category"),
        ("no_basis", "evidence or judgment"),
        ("conviction", "computed conviction"),
        ("extra", "Extra inputs"),
        ("too_long", "length cap"),
        ("nonfinite", "finite"),
    ],
)
def test_invalid_rationale_contracts_are_actionable(
    settings: Settings, change: str, message: str
) -> None:
    raw: dict[str, Any] = deepcopy(rationale_payload())
    if change == "one_risk":
        raw["risk_flags"] = raw["risk_flags"][:1]
    elif change == "unknown_risk":
        raw["risk_flags"][0]["category"] = "mystery"
    elif change == "no_basis":
        raw["risk_flags"][1]["evidence_ids"] = []
    elif change == "conviction":
        raw["conviction"]["level"] = "Low"
    elif change == "extra":
        raw["hidden_section"] = "Unsupported"
    elif change == "too_long":
        raw["acquirer_overview"] = "x" * (settings.evidence.validation.section_chars + 1)
    else:
        raw["claims"][0]["value"] = float("nan")
    with pytest.raises(ValidationFailure, match=message):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)
