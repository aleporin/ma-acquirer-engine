"""Measure routing and ablations separately from the normal pipeline.

Owns: Observation cohorts, recovery/reviewer counters, and explicit missing evidence.
Does not own: Running providers or assigning unmeasured rubric quality.
"""

import json
from pathlib import Path

from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.settings import LayerSpec, Settings
from evals.graders import distinct
from evals.phase1 import PreparedEvaluation
from evals.phase3 import _load_runs, prepare_phase3
from evals.scorecard import LayerResult, Metric


def _routing_metrics(runs: list[AnalystRun]) -> dict[str, Metric]:
    values: dict[str, float] = {}
    for mode in sorted({r.mode for r in runs}):
        group = [r for r in runs if r.mode == mode]
        full = [r for r in group if r.tools_enabled and r.reviewer_enabled]
        pages = [p for r in full for p in r.pages]
        flagged = sum(v.decision == "revise" for r in full if r.review for v in r.review.verdicts)
        if pages:
            values[f"{mode}_reviewer_flag_rate"] = flagged / len(pages)
            values[f"{mode}_escalation_rate"] = sum(
                any(a.stage == "escalation" for a in p.attempts) for p in pages
            ) / len(pages)
        disabled = [p for r in group if not r.tools_enabled for p in r.pages]
        values[f"{mode}_tools_disabled_pages"] = len(disabled)
        if disabled:
            values[f"{mode}_tools_disabled_validation_failure_rate"] = sum(
                p.status == "failed" and any("comp" in error for error in p.errors)
                for p in disabled
            ) / len(disabled)
        values[f"{mode}_reviewer_disabled_runs"] = sum(
            r.tools_enabled and not r.reviewer_enabled for r in group
        )
        values[f"{mode}_uncertain_cost_bound_usd"] = sum(r.uncertain_cost_bound_usd for r in group)
    return {
        name: Metric(
            value=value,
            direction="lower"
            if "cost" in name or "escalation" in name or "flag_rate" in name
            else "higher",
        )
        for name, value in values.items()
    }


def _operations(baseline: LayerResult, runs: list[AnalystRun], settings: Settings) -> LayerResult:
    metrics = dict(baseline.metrics) | _routing_metrics(runs)
    full = [r for r in runs if r.mode == "live" and r.tools_enabled and r.reviewer_enabled]
    if full:
        complete = all(
            len(r.pages) == settings.scoring.top_k
            and all(
                p.status == "verified"
                and p.claims_total > 0
                and p.claims_verified == p.claims_total
                for p in r.pages
            )
            and r.review is not None
            and not r.review.errors
            for r in full
        )
        ablated = metrics.get("live_tools_disabled_validation_failure_rate")
        compared = metrics.get("live_reviewer_disabled_runs")
        gate = (
            complete
            and ablated is not None
            and ablated.value == 1
            and compared is not None
            and compared.value > 0
        )
        metrics["live_phase3_latency_gate_met"] = metrics.pop("live_gate_met")
        metrics["live_gate_met"] = Metric(value=float(gate), direction="higher")
        return baseline.model_copy(
            update={"metrics": metrics, "status": "passed" if gate else "failed"}
        )
    return baseline.model_copy(update={"metrics": metrics})


def prepare_phase4(
    prepared: PreparedEvaluation, paths: list[Path], settings: Settings
) -> PreparedEvaluation:
    """Preserve complete observations while measuring intentional failures separately.

    Args:
        prepared: Earlier deterministic eval layers.
        paths: Explicit saved observations, never new provider calls.
        settings: Required page count and measurement configuration.
    Returns:
        Baseline metrics, paired reviewer overlap, and isolated ablation evidence.
    """
    if not paths:
        return prepared
    runs = _load_runs(paths, settings)
    baseline_paths = [
        path
        for path, run in zip(paths, runs, strict=True)
        if run.tools_enabled and run.reviewer_enabled
    ]
    combined = prepare_phase3(prepared, baseline_paths, settings)
    if not baseline_paths:
        return combined
    graders = dict(combined.graders)
    original_ops = graders[6]
    graders[6] = lambda layer: _operations(original_ops(layer), runs, settings)
    full = [r for r in runs if r.tools_enabled and r.reviewer_enabled]
    original_distinct = graders[3]
    graders[3] = lambda layer: _review_overlap(original_distinct(layer), layer, full, settings)
    artifacts = combined.artifacts | {
        "routing_observations.json": json.dumps(
            {
                "scope": "paired reviewer overlap; rubric quality remains unmeasured",
                "runs": [r.model_dump(mode="json") for r in runs],
            },
            indent=2,
        )
        + "\n"
    }
    return PreparedEvaluation(graders, artifacts)


def _review_overlap(
    baseline: LayerResult, layer: LayerSpec, runs: list[AnalystRun], settings: Settings
) -> LayerResult:
    before = [r.model_copy(update={"pages": r.before_review}) for r in runs if r.before_review]
    if not before:
        return baseline
    metrics = distinct.grade(layer, before, settings.analyst).metrics
    return baseline.model_copy(
        update={
            "metrics": dict(baseline.metrics)
            | {f"before_review_{name}": value for name, value in metrics.items()}
        }
    )
