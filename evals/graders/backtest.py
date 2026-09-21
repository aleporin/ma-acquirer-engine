"""Expose measured temporal ranking quality as an evaluation layer.

Owns: Translating backtest results into scorecard metrics.
Does not own: Fitting the ranker or treating weak signal as implementation failure.
"""

from acquirer_engine.settings import LayerSpec
from evals.ranking.report import BacktestReport
from evals.scorecard import LayerResult, Metric


def grade(layer: LayerSpec, report: BacktestReport | None = None) -> LayerResult:
    """Report ranking, baseline, and paired lift measurements.

    Args:
        layer: Registered layer identity.
        report: Completed temporal holdout, absent for the historical stub harness.
    Returns:
        Measured metrics; passed means measured successfully, not positive lift.
    """
    if report is None:
        return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    metrics = {
        f"{method}_{name}": Metric(value=value, direction="higher")
        for method, values in report.metrics.items()
        for name, value in values.items()
    }
    for method, values in report.lift.items():
        for name, interval in values.items():
            for bound, value in interval.model_dump().items():
                metrics[f"lift_vs_{method}_{name}_{bound}"] = Metric(
                    value=value, direction="higher"
                )
    return LayerResult(
        id=layer.id, name=layer.name, selected=True, status="passed", metrics=metrics
    )
