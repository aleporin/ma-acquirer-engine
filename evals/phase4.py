"""Measure routing and ablations separately from the normal pipeline.

Owns: Observation cohorts, recovery/reviewer counters, and explicit missing evidence.
Does not own: Running providers or assigning unmeasured rubric quality.
"""

import json
from pathlib import Path

from acquirer_engine.llm.results import AnalystRun, PageAttempt, PageResult
from acquirer_engine.settings import LayerSpec, Settings
from evals.graders import distinct, ops
from evals.observations import load_runs
from evals.phase1 import PreparedEvaluation
from evals.phase3 import prepare_phase3
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
        values.update({f"{mode}_{k}": v for k, v in _tools_metrics(group).items()})
        values[f"{mode}_reviewer_enabled_runs"] = len(full)
        values[f"{mode}_reviewer_disabled_runs"] = sum(
            r.tools_enabled and not r.reviewer_enabled for r in group
        )
        values[f"{mode}_uncertain_cost_bound_usd"] = sum(r.uncertain_cost_bound_usd for r in group)
    return {
        name: Metric(
            value=value,
            direction="lower"
            if any(term in name for term in ("cost", "escalation", "flag_rate", "termination"))
            else "higher",
        )
        for name, value in values.items()
    }


def _rejected_without_tools(page: PageResult) -> bool:
    attempts: list[PageAttempt | PageResult] = list(page.attempts) or [page]
    return (
        page.status == "failed"
        and not page.tools
        and all(a.status == "failed" for a in attempts)
        and any("requires a retrieved Closed comp" in e for a in attempts for e in a.errors)
    )


def _tools_metrics(runs: list[AnalystRun]) -> dict[str, float]:
    pages = [p for r in runs if not r.tools_enabled for p in r.pages]
    values: dict[str, float] = {"tools_disabled_pages": len(pages)}
    if pages:
        values.update(
            {
                "tools_disabled_validation_failure_rate": sum(
                    p.status == "failed" and any("comp" in e for e in p.errors) for p in pages
                )
                / len(pages),
                "tools_disabled_evidence_rejection_rate": sum(
                    _rejected_without_tools(p) for p in pages
                )
                / len(pages),
                "tools_disabled_budget_termination_rate": sum(
                    any("Run USD budget" in e for e in p.errors) for p in pages
                )
                / len(pages),
                "tools_disabled_deadline_termination_rate": sum(
                    any("Run deadline exceeded" in e for e in p.errors) for p in pages
                )
                / len(pages),
            }
        )
    return values


def _complete(run: AnalystRun, expected: int) -> bool:
    repaired = [
        next((a for a in reversed(p.attempts) if a.stage != "revision"), p) for p in run.pages
    ]
    return (
        len(run.pages) == len({p.acquirer for p in run.pages}) == expected
        and all(
            p.status == "verified" and p.claims_total > 0 and p.claims_verified == p.claims_total
            for p in [*run.pages, *repaired]
        )
        and (not run.reviewer_enabled or _review_complete(run))
    )


def _review_complete(run: AnalystRun) -> bool:
    if run.review is None or run.review.errors:
        return False
    names = [v.acquirer for v in run.review.verdicts]
    return len(names) == len(set(names)) and set(names) == {p.acquirer for p in run.pages}


def _phase_gate(runs: list[AnalystRun], settings: Settings) -> bool:
    live = [r for r in runs if r.mode == "live"]
    enabled = [r for r in live if r.tools_enabled]
    disabled = [r for r in live if not r.tools_enabled]
    if not enabled or not disabled or {r.reviewer_enabled for r in enabled} != {True, False}:
        return False
    names = {p.acquirer for p in enabled[0].pages}
    return (
        all(_complete(r, settings.scoring.top_k) for r in enabled)
        and all(len(r.pages) == len(names) and {p.acquirer for p in r.pages} == names for r in live)
        and all(_rejected_without_tools(p) for r in disabled for p in r.pages)
    )


def _operations(baseline: LayerResult, runs: list[AnalystRun], settings: Settings) -> LayerResult:
    metrics = dict(baseline.metrics) | _routing_metrics(runs)
    if any(r.mode == "live" and r.tools_enabled for r in runs):
        gate = _phase_gate(runs, settings)
        if "live_gate_met" in metrics:
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
    runs = load_runs(paths, settings)
    baseline_paths = [
        path
        for path, run in zip(paths, runs, strict=True)
        if run.tools_enabled and run.reviewer_enabled == settings.analyst.reviewer_enabled
    ]
    combined = prepare_phase3(prepared, baseline_paths, settings)
    graders = dict(combined.graders)
    original_ops = graders.get(6, ops.grade)
    graders[6] = lambda layer: _operations(original_ops(layer), runs, settings)
    full = [r for r in runs if r.tools_enabled and r.reviewer_enabled]
    original_distinct = graders.get(3, distinct.grade)
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
