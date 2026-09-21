"""Report repeated ranking identity and independent conviction levels.

Owns: Ranking stability measurements and the current phase's conviction gate.
Does not own: Forcing levels or judging rationale stability.
"""

from dataclasses import dataclass

from acquirer_engine.settings import LayerSpec
from evals.scorecard import LayerResult, Metric


@dataclass(frozen=True)
class RankingStability:
    """Observed repeated-run agreement and level count."""

    identity: float
    conviction_agreement: float
    levels: int
    minimum_levels: int


def grade(layer: LayerSpec, report: RankingStability | None = None) -> LayerResult:
    """Report only the ranking portion of stability in this phase.

    Args:
        layer: Registered layer identity.
        report: Repeated ranking measurements, absent for the historical stub.
    Returns:
        Failure when identity changes or the intermediate level gate is unmet.
    """
    if report is None:
        return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    passed = (
        report.identity == report.conviction_agreement == 1
        and report.levels >= report.minimum_levels
    )
    return LayerResult(
        id=layer.id,
        name=layer.name,
        selected=True,
        status="passed" if passed else "failed",
        metrics={
            "top_k_identity": Metric(value=report.identity, direction="higher"),
            "conviction_agreement": Metric(value=report.conviction_agreement, direction="higher"),
            "conviction_levels": Metric(value=report.levels, direction="higher"),
        },
    )
