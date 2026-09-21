"""Measure ranking quality and paired bootstrap lift.

Owns: Explicit metric definitions and seeded transaction-level intervals.
Does not own: Choosing or fitting the ranker.
"""

import math
from collections.abc import Sequence
from random import Random
from statistics import fmean

import pandas as pd
from pydantic import BaseModel


class Interval(BaseModel):
    """A measured difference and its percentile bootstrap bounds."""

    mean: float
    low: float
    high: float


def metrics_at_rank(rank: int | None, k: int) -> dict[str, float]:
    """Compute recall@k, full-list MRR, and nDCG@k for one relevant buyer.

    Args:
        rank: One-based rank, or null for an unavailable buyer.
        k: Retrieval cutoff.
    Returns:
        Zero credit for unavailable labels; MRR is not truncated at k.
    """
    hit = rank is not None and rank <= k
    return {
        "recall_at_k": float(hit),
        "mrr": 1 / rank if rank else 0.0,
        "ndcg_at_k": 1 / math.log2(rank + 1) if hit and rank else 0.0,
    }


def ranking_metrics(ranking: Sequence[str], truth: str, k: int) -> dict[str, float]:
    """Measure one label against an ordered candidate list.

    Args:
        ranking: Unique buyer names in ranked order.
        truth: Observed held-out buyer.
        k: Retrieval cutoff.
    Returns:
        Recall@k, full-list reciprocal rank, and nDCG@k.
    """
    return metrics_at_rank(ranking.index(truth) + 1 if truth in ranking else None, k)


def paired_lift(
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    seed: int,
    samples: int,
    confidence: float,
) -> Interval:
    """Bootstrap paired per-transaction differences with an injected seed.

    Args:
        candidate: Ranker measurements in query order.
        baseline: Baseline measurements for the same queries.
        seed: Reproducible resampling seed.
        samples: Number of bootstrap replicates.
        confidence: Central interval probability.
    Returns:
        Mean lift and percentile interval; negative results remain negative.
    Raises:
        ValueError: Inputs cannot define paired bootstrap samples.
    """
    if not candidate or len(candidate) != len(baseline) or samples < 1 or not 0 < confidence < 1:
        raise ValueError("Bootstrap requires nonempty paired measurements and valid settings")
    differences = [left - right for left, right in zip(candidate, baseline, strict=True)]
    rng = Random(seed)
    draws = pd.Series([fmean(rng.choices(differences, k=len(differences))) for _ in range(samples)])
    tail = (1 - confidence) / 2
    return Interval(
        mean=fmean(differences),
        low=float(draws.quantile(tail)),
        high=float(draws.quantile(1 - tail)),
    )
