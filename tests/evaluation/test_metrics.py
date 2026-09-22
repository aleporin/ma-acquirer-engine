"""Verify exact ranking metrics and reproducible paired uncertainty.

Owns: Rank arithmetic, missing labels, and bootstrap intervals.
Does not own: Fitting candidate features.
"""

import math

import pytest

from evals.ranking.metrics import metrics_at_rank, paired_lift


def test_known_rank_metrics_and_unseen_label() -> None:
    values = metrics_at_rank(2, 2)
    assert values == {"recall_at_k": 1, "mrr": 0.5, "ndcg_at_k": 1 / math.log2(3)}
    assert metrics_at_rank(None, 10) == {
        "recall_at_k": 0,
        "mrr": 0,
        "ndcg_at_k": 0,
    }
    assert metrics_at_rank(3, 2)["mrr"] == pytest.approx(1 / 3)
    assert metrics_at_rank(3, 2)["ndcg_at_k"] == 0


def test_paired_bootstrap_preserves_pairing_and_seed() -> None:
    values = [0.0, 1.0, 0.0, 1.0]
    zero = paired_lift(values, values, seed=7, samples=100, confidence=0.95)
    assert zero.mean == zero.low == zero.high == 0
    result = paired_lift([1.0] * 4, values, seed=7, samples=100, confidence=0.95)
    assert result.mean == 0.5
    assert result.low <= result.mean <= result.high
    assert result == paired_lift([1.0] * 4, values, seed=7, samples=100, confidence=0.95)


def test_mismatched_pairs_cannot_produce_an_interval() -> None:
    with pytest.raises(ValueError):
        paired_lift([1.0], [], seed=7, samples=100, confidence=0.95)
