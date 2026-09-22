"""Apply explicit exclusions after the measured base ranking.

Owns: Same-type sector-profile similarity and transparent score penalties.
Does not own: Training, changing feature priors, or feedback persistence.
"""

from collections import Counter
from math import sqrt
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from acquirer_engine.errors import DataError
from acquirer_engine.features.acquirer import AcquirerHistory, FittedFeatures
from acquirer_engine.feedback.state import FeedbackState
from acquirer_engine.ranking.config import RankingConfig
from acquirer_engine.ranking.conviction import conviction
from acquirer_engine.ranking.scorer import RankedAcquirer


class FeedbackPolicy(BaseModel):
    """Maximum multiplicative penalty; configured independently of base scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    similarity_penalty: Annotated[float, Field(ge=0, lt=1)]


def _similarity(left: AcquirerHistory, right: AcquirerHistory) -> float:
    if left.acquirer_type != right.acquirer_type:
        return 0.0
    a, b = Counter(r.sector for r in left.rows), Counter(r.sector for r in right.rows)
    numerator = sum(count * b[sector] for sector, count in a.items())
    denominator = sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))
    return min(1.0, numerator / denominator) if denominator else 0.0


def apply_feedback(
    ranked: list[RankedAcquirer],
    fitted: FittedFeatures,
    state: FeedbackState,
    penalty: float,
    config: RankingConfig,
) -> list[RankedAcquirer]:
    """Exclude flags and discount scores by the closest flagged sector profile.

    Args:
        ranked: Original scored candidates, with unchanged signal contributions.
        fitted: Eligible historical activity used to measure similarity.
        state: Exact buyer exclusions.
        penalty: Validated maximum fractional penalty from YAML.
        config: Code conviction policy, applied to the adjusted score.
    Returns:
        Stable reranking; original contributions retain the base score for audit.
    Raises:
        DataError: A saved exclusion is absent from eligible history.
    """
    excluded = {flag.acquirer for flag in state.flags}
    if excluded - fitted.acquirers.keys():
        raise DataError("Saved feedback refers to an acquirer absent from eligible history")
    adjusted = []
    for item in ranked:
        if item.acquirer in excluded:
            continue
        similarity = max(
            (
                _similarity(fitted.acquirers[item.acquirer], fitted.acquirers[name])
                for name in excluded
            ),
            default=0.0,
        )
        score = item.score * (1 - penalty * similarity)
        adjusted.append(
            item.model_copy(
                update={
                    "score": score,
                    "conviction": conviction(score, item.relevant_deals, config),
                }
            )
        )
    return sorted(adjusted, key=lambda item: (-item.score, item.acquirer.casefold(), item.acquirer))
