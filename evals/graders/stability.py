"""Report repeated ranking identity and independent conviction levels.

Owns: Ranking repeatability checks and diagnostic conviction diversity.
Does not own: Forcing levels or judging rationale stability.
"""

from dataclasses import dataclass

from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.llm.results import AnalystRun
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
        Failure when observed ranks or convictions change; diversity is diagnostic.
    """
    if report is None:
        return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    passed = report.identity == report.conviction_agreement == 1 and report.levels > 0
    return LayerResult(
        id=layer.id,
        name=layer.name,
        selected=True,
        status="passed" if passed else "failed",
        metrics={
            "top_k_identity": Metric(value=report.identity, direction="higher"),
            "conviction_agreement": Metric(value=report.conviction_agreement, direction="higher"),
            "conviction_levels": Metric(value=report.levels, direction="higher"),
            "conviction_diversity_target_met": Metric(
                value=float(report.levels >= report.minimum_levels), direction="higher"
            ),
        },
    )


def with_validation(
    ranking: LayerResult, runs: list[AnalystRun], config: AnalystConfig
) -> LayerResult:
    """Add all-run page acceptance without hiding inherited ranking failures.

    Args:
        ranking: Existing ranking stability result.
        runs: Independent recorded executions, grouped by mode.
        config: Required repeat count.
    Returns:
        Extended measurements; replay repeats never stand for live stochasticity.
    """
    metrics = dict(ranking.metrics)
    failed = ranking.status == "failed"
    for mode in sorted({run.mode for run in runs}):
        group = [run for run in runs if run.mode == mode]
        metrics[f"{mode}_validation_runs"] = Metric(value=len(group), direction="higher")
        if len(group) != config.stability_runs:
            continue
        names = [p.acquirer for p in group[0].pages]
        same = all([p.acquirer for p in run.pages] == names for run in group)
        rate = (
            (
                sum(
                    all(run.pages[i].status == "verified" for run in group)
                    for i in range(len(names))
                )
                / len(names)
            )
            if same and names
            else 0
        )
        metrics[f"{mode}_validation_pass_{config.stability_runs}"] = Metric(
            value=rate, direction="higher"
        )
        failed |= rate != 1
    return ranking.model_copy(
        update={"metrics": metrics, "status": "failed" if failed else "passed"}
    )
