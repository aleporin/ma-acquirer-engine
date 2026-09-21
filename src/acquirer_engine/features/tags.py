"""Down-weight ubiquitous rationale tags.

Owns: Training-only inverse document frequency.
Does not own: Semantic tag generation or prompt text.
"""

import math
from collections import Counter
from collections.abc import Sequence

from acquirer_engine.data.schema import Transaction


def parse_tags(value: str) -> frozenset[str]:
    """Return unique nonempty pipe-delimited tags.

    Args:
        value: Validated CSV tag string.
    Returns:
        Unique trimmed tags.
    """
    return frozenset(tag.strip() for tag in value.split("|") if tag.strip())


def idf_weights(rows: Sequence[Transaction]) -> dict[str, float]:
    """Compute smoothed IDF; a ubiquitous tag has zero weight.

    Args:
        rows: Training transactions only.
    Returns:
        Deterministically ordered tag weights.
    """
    counts = Counter(tag for row in rows for tag in parse_tags(row.strategic_rationale_tags))
    return {tag: math.log((len(rows) + 1) / (counts[tag] + 1)) for tag in sorted(counts)}
