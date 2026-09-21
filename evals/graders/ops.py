"""Measure execution cost, latency, and tool use from recorded runs.

Owns: Arithmetic on observed usage, with replay and live results kept distinct.
Does not own: Estimating unreported billing or running providers.
"""

from collections import Counter

from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.settings import LayerSpec
from evals.scorecard import LayerResult, Metric


def percentile(values: list[float], fraction: float) -> float:
    """Interpolate an empirical percentile; callers supply nonempty observations."""
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def _metrics(runs: list[AnalystRun], config: AnalystConfig) -> dict[str, Metric]:
    calls = [call for run in runs for call in run.calls]
    pages = [page for run in runs for page in run.pages]
    values = {
        "runs": len(runs),
        "pages": len(pages),
        "responses": len(calls),
        "cost_usd": sum(call.cost_usd for call in calls),
        "run_p50_seconds": percentile([run.latency_seconds for run in runs], 0.5),
        "run_p95_seconds": percentile([run.latency_seconds for run in runs], 0.95),
    }
    for metric in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        values[metric] = sum(getattr(call, metric) for call in calls)
    if calls:
        values["request_p50_ms"] = percentile([c.latency_ms for c in calls], 0.5)
        values["request_p95_ms"] = percentile([c.latency_ms for c in calls], 0.95)
    populations = Counter(page.acquirer_type for page in pages)
    selections = Counter((p.acquirer_type, tool) for p in pages for tool in set(p.tools))
    for (kind, tool), count in selections.items():
        values[f"{kind.replace(' ', '_').lower()}_{tool}_page_rate"] = count / populations[kind]
    if runs[0].mode == "live":
        values["gate_met"] = float(
            all(
                run.latency_seconds < config.latency_target_seconds
                and bool(run.pages)
                and all(p.status == "verified" for p in run.pages)
                and sum(c.cost_usd for c in run.calls) > 0
                for run in runs
            )
        )
    return {
        name: Metric(
            value=value,
            direction="lower" if "seconds" in name or "ms" in name or "cost" in name else "higher",
        )
        for name, value in values.items()
    }


def grade(
    layer: LayerSpec, runs: list[AnalystRun] | None = None, config: AnalystConfig | None = None
) -> LayerResult:
    """Report observed operations; live gate failure stays visible.

    Args:
        layer: Registered layer identity.
        runs: Stored observations; never new provider calls.
        config: Shared latency target.
    Returns:
        Mode-prefixed metrics, or an unmeasured stub when no run exists.
    """
    if not runs or config is None:
        return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    metrics = {
        f"{mode}_{name}": metric
        for mode in sorted({run.mode for run in runs})
        for name, metric in _metrics([r for r in runs if r.mode == mode], config).items()
    }
    failed = "live_gate_met" in metrics and metrics["live_gate_met"].value == 0
    return LayerResult(
        id=layer.id,
        name=layer.name,
        selected=True,
        status="failed" if failed else "passed",
        metrics=metrics,
    )
