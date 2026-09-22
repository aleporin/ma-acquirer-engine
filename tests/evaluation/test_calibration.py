"""Specify agreement and uncertainty without treating abstention as a verdict.

Owns: Independent numeric examples and repeated-buyer sampling checks.
Does not own: Provider judgments or human labeling.
"""

import pytest

from evals.judges.calibration import agreement, cohen_kappa


def test_kappa_removes_chance_agreement() -> None:
    assert cohen_kappa(["Pass", "Pass", "Fail", "Fail"], ["Pass", "Fail", "Pass", "Fail"]) == 0
    assert cohen_kappa(["Pass", "Fail"], ["Pass", "Fail"]) == 1
    assert cohen_kappa(["Pass", "Fail"], ["Fail", "Pass"]) == -1


def test_degenerate_agreement_is_undefined_not_perfect() -> None:
    assert cohen_kappa(["Pass", "Pass"], ["Pass", "Pass"]) is None
    assert cohen_kappa([], []) is None
    with pytest.raises(ValueError, match="same length"):
        cohen_kappa(["Pass"], [])


def test_unknown_is_an_abstention_with_explicit_coverage() -> None:
    result = agreement(
        ["Pass", "Unknown", "Fail"],
        ["Pass", "Fail", "Fail"],
        ["buyer-a", "buyer-b", "buyer-c"],
        seed=7,
        samples=100,
        confidence=0.95,
    )
    assert result.total == 3 and result.compared == 2 and result.abstentions == 1
    assert result.kappa == 1 and result.agreement == 1
    assert result.clusters == 2
    assert result.valid_bootstraps < 100


def test_bootstrap_keeps_repeated_buyer_pages_together() -> None:
    result = agreement(
        ["Pass", "Fail", "Pass", "Fail"],
        ["Pass", "Fail", "Fail", "Pass"],
        ["a", "a", "b", "b"],
        seed=7,
        samples=500,
        confidence=0.95,
    )
    assert result.kappa == 0 and result.clusters == 2
    assert result.interval == (-1, 1)
    assert result.valid_bootstraps == 500
    repeated = agreement(
        ["Pass", "Fail", "Pass", "Fail"],
        ["Pass", "Fail", "Fail", "Pass"],
        ["a", "a", "b", "b"],
        seed=7,
        samples=500,
        confidence=0.95,
    )
    assert repeated == result


def test_empty_comparison_cannot_claim_a_confidence_interval() -> None:
    result = agreement(["Unknown"], ["Pass"], ["a"], seed=7, samples=50, confidence=0.95)
    assert result.compared == 0
    assert result.kappa is None and result.interval is None
    assert result.valid_bootstraps == 0
