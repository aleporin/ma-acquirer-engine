"""Exercise numeric, provenance, and prose validation boundaries.

Owns: Acceptance of true claims and specific rejection of invented evidence.
Does not own: Semantic assessment of an investment thesis.
"""

from copy import deepcopy
from typing import Any

import pytest
from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.validation.claims import validate_rationale

from acquirer_engine.errors import EvidenceError, ValidationFailure
from acquirer_engine.settings import Settings
from tests.fixtures.rationale import evidence_context, rationale_payload


def test_true_page_passes_with_rounding_and_external_notes(settings: Settings) -> None:
    raw = rationale_payload()
    raw["outside_dataset_notes"] = (
        "Unverified outside information from 2025; 999 is not a dataset claim."
    )
    page = validate_rationale(raw, evidence_context(settings), settings.evidence.validation)
    assert page.claims[2].value == 13.6
    assert page.outside_dataset_notes


@pytest.mark.parametrize(
    ("metric", "value", "evidence_id", "message"),
    [
        ("ev_ebitda_multiple", 99, "MA-2020-0010", "value mismatch"),
        ("ev_ebitda_multiple", 13.6, "MA-2020-9999", "unknown evidence"),
        ("invented_metric", 13.6, "MA-2020-0010", "unknown numeric metric"),
        ("deal_year", 2020.04, "MA-2020-0010", "value mismatch"),
        ("deal_count", 4.04, "stat:deal_count:Buyer%20A", "value mismatch"),
    ],
)
def test_claims_must_resolve_to_the_exact_metric(
    settings: Settings, metric: str, value: float, evidence_id: str, message: str
) -> None:
    raw: dict[str, Any] = deepcopy(rationale_payload())
    raw["claims"][2] = {"metric": metric, "value": value, "evidence_id": evidence_id}
    with pytest.raises(ValidationFailure, match=message):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


@pytest.mark.parametrize("number", ["$999M", "999%", "999x", "2025", "1,999", "-999", "9.99e2"])
def test_prose_numbers_require_explicit_claims(settings: Settings, number: str) -> None:
    raw = rationale_payload()
    raw["strategic_fit_thesis"] = f"Recorded capacity is {number}."
    with pytest.raises(ValidationFailure, match="stray number"):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


def test_transaction_ids_are_references_not_stray_numbers(settings: Settings) -> None:
    raw = rationale_payload()
    raw["strategic_fit_thesis"] = "Prior activity includes MA-2020-0001."
    validate_rationale(raw, evidence_context(settings), settings.evidence.validation)
    raw["strategic_fit_thesis"] = "Prior activity includes MA-2020-9999."
    with pytest.raises(ValidationFailure, match="unknown evidence"):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


def test_banned_boilerplate_ignores_case_and_whitespace(settings: Settings) -> None:
    raw = rationale_payload()
    raw["acquirer_overview"] = "A LEADING\nhealthcare company with ambition."
    with pytest.raises(ValidationFailure, match="banned phrase"):
        validate_rationale(raw, evidence_context(settings), settings.evidence.validation)


@pytest.mark.parametrize("kind", ["missing", "own_only", "pending", "uncited_multiple"])
def test_valuation_requires_separately_retrieved_closed_comps(
    settings: Settings, kind: str
) -> None:
    context = evidence_context(settings)
    raw: dict[str, Any] = deepcopy(rationale_payload())
    if kind == "missing":
        raw["valuation_context"]["comps"] = []
    elif kind == "own_only":
        context = EvidenceContext(core=context.core)
        raw["valuation_context"]["comps"] = [{"evidence_id": "MA-2020-0001"}]
    elif kind == "pending":
        row = context.comparable_deals[0].model_copy(
            update={"outcome": "Pending", "days_to_close": None}
        )
        context = EvidenceContext(core=context.core, comparable_deals=(row,))
    else:
        raw["claims"] = raw["claims"][:2]
    with pytest.raises(ValidationFailure, match="valuation_context"):
        validate_rationale(raw, context, settings.evidence.validation)


def test_conflicting_evidence_cannot_overwrite_a_core_row(settings: Settings) -> None:
    context = evidence_context(settings)
    conflicting = context.core.deals[0].model_copy(update={"deal_size_mm": 999})
    with pytest.raises(EvidenceError, match="conflicting evidence"):
        validate_rationale(
            rationale_payload(),
            EvidenceContext(core=context.core, comparable_deals=(conflicting,)),
            settings.evidence.validation,
        )
