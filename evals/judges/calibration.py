"""Measure agreement while preserving abstentions and repeated-buyer dependence.

Owns: Pure Cohen kappa and seeded cluster-bootstrap confidence intervals.
Does not own: Human labeling, judgment calls, or pass thresholds.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from random import Random

from pydantic import BaseModel, ConfigDict, FiniteFloat, NonNegativeInt


class Agreement(BaseModel):
    """Report support and undefined statistics instead of inventing agreement."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    total: NonNegativeInt
    compared: NonNegativeInt
    abstentions: NonNegativeInt
    clusters: NonNegativeInt
    agreement: FiniteFloat | None
    kappa: FiniteFloat | None
    interval: tuple[FiniteFloat, FiniteFloat] | None
    valid_bootstraps: NonNegativeInt


def cohen_kappa(left: Sequence[str], right: Sequence[str]) -> float | None:
    """Subtract marginal chance agreement from observed agreement.

    Args:
        left, right: Aligned categorical observations with abstentions removed.
    Returns:
        Kappa, or None when no comparison or no marginal variation exists.
    Raises:
        ValueError: Sequences are not aligned.
    """
    if len(left) != len(right):
        raise ValueError("Agreement sequences must have the same length")
    if not left:
        return None
    n = len(left)
    counts_left, counts_right = Counter(left), Counter(right)
    expected = sum(v * counts_right[k] for k, v in counts_left.items()) / n**2
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / n
    return (observed - expected) / (1 - expected) if expected < 1 else None


def _percentile(values: list[float], probability: float) -> float:
    index = (len(values) - 1) * probability
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def _bootstrap(pairs: list[tuple[str, str, str]], seed: int, samples: int) -> list[float]:
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for a, b, cluster in pairs:
        groups[cluster].append((a, b))
    rng = Random(seed)
    keys = sorted(groups)
    values = []
    for _ in range(samples if keys else 0):
        selected = rng.choices(keys, k=len(keys))
        sample = [pair for key in selected for pair in groups[key]]
        value = cohen_kappa([a for a, _ in sample], [b for _, b in sample])
        if value is not None:
            values.append(value)
    return sorted(values)


def agreement(
    left: Sequence[str],
    right: Sequence[str],
    clusters: Sequence[str],
    *,
    seed: int,
    samples: int,
    confidence: float,
) -> Agreement:
    """Compare answered votes and resample whole buyers, retaining all their pages.

    Args:
        left, right, clusters: Aligned votes and repeated-buyer identities.
        seed, samples, confidence: Explicit bootstrap policy from configuration.
    Returns:
        Agreement, interval, comparison coverage, and valid bootstrap count.
    Raises:
        ValueError: Inputs or bootstrap policy are invalid.
    """
    if len(left) != len(right) or len(left) != len(clusters):
        raise ValueError("Agreement sequences must have the same length")
    if samples < 1 or not 0 < confidence < 1:
        raise ValueError("Invalid bootstrap policy")
    if not set(left).union(right) <= {"Pass", "Fail", "Unknown"}:
        raise ValueError("Votes must be Pass, Fail, or Unknown")
    pairs = [
        (a, b, c) for a, b, c in zip(left, right, clusters, strict=True) if "Unknown" not in (a, b)
    ]
    values = _bootstrap(pairs, seed, samples)
    tail = (1 - confidence) / 2
    interval = (_percentile(values, tail), _percentile(values, 1 - tail)) if values else None
    return Agreement(
        total=len(left),
        compared=len(pairs),
        abstentions=len(left) - len(pairs),
        clusters=len({c for _, _, c in pairs}),
        agreement=sum(a == b for a, b, _ in pairs) / len(pairs) if pairs else None,
        kappa=cohen_kappa([a for a, _, _ in pairs], [b for _, b, _ in pairs]),
        interval=interval,
        valid_bootstraps=len(values),
    )
