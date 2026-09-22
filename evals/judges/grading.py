"""Add recorded identification and calibrated rubric judgments to offline evals.

Owns: Layer three/four thresholds and portable judge measurement artifacts.
Does not own: Provider execution, human labeling, or earlier phase gates.
"""

import json
from pathlib import Path

from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import LayerSpec
from evals.graders import distinct
from evals.harness import PreparedEvaluation
from evals.judges.plan import JudgePlan
from evals.judges.prepare import validate_cohort
from evals.judges.reporting import JudgeSummary, summarize
from evals.judges.results import JudgeRun
from evals.judges.schema import Dimension
from evals.scorecard import LayerResult, Metric


def _measured(run: JudgeRun) -> bool:
    return (run.observation_mode or run.mode) == "live" and not run.source_dirty


def _rubric(layer: LayerSpec, summary: JudgeSummary, plan: JudgePlan, run: JudgeRun) -> LayerResult:
    metrics = {
        "human_pages": Metric(value=summary.human_pages, direction="higher"),
        "request_failures": Metric(value=summary.request_failures, direction="lower"),
    }
    passed = _measured(run) and summary.request_failures == 0
    for role, dimensions in summary.human_agreement.items():
        overall = dimensions["all"]
        passed = passed and overall.kappa is not None and overall.kappa >= plan.config.kappa_min
        passed = passed and overall.interval is not None
        for dimension, comparison in dimensions.items():
            prefix = role if dimension == "all" else f"{role}_{dimension}"
            metrics[prefix + "_compared"] = Metric(value=comparison.compared, direction="higher")
            metrics[prefix + "_abstentions"] = Metric(
                value=comparison.abstentions, direction="lower"
            )
            if comparison.kappa is not None:
                metrics[prefix + "_kappa"] = Metric(value=comparison.kappa, direction="higher")
            if comparison.interval is not None:
                metrics[prefix + "_kappa_low"] = Metric(
                    value=comparison.interval[0], direction="higher"
                )
                metrics[prefix + "_kappa_high"] = Metric(
                    value=comparison.interval[1], direction="higher"
                )
    return LayerResult(
        id=layer.id,
        name=layer.name,
        selected=True,
        status="passed" if passed else "failed",
        metrics=metrics,
    )


def _identification(
    baseline: LayerResult, summary: JudgeSummary, plan: JudgePlan, run: JudgeRun
) -> LayerResult:
    metrics = dict(baseline.metrics)
    passed = _measured(run) and baseline.status != "failed" and summary.request_failures == 0
    for cohort, roles in summary.identification.items():
        for role, rate in roles.items():
            prefix = f"{cohort}_{role}_identification"
            metrics[prefix + "_answered"] = Metric(value=rate.answered, direction="higher")
            metrics[prefix + "_abstentions"] = Metric(value=rate.unknown, direction="lower")
            if rate.accuracy is not None:
                metrics[prefix + "_accuracy"] = Metric(value=rate.accuracy, direction="higher")
            if cohort == "reviewer_disabled":
                passed = (
                    passed
                    and rate.accuracy is not None
                    and rate.accuracy >= plan.config.identification_accuracy_min
                )
    return baseline.model_copy(
        update={"selected": True, "metrics": metrics, "status": "passed" if passed else "failed"}
    )


def _check_labels(plan: JudgePlan) -> None:
    expected = {
        (c.case_id, d) for c in plan.corpus.cases if c.stage == "after_review" for d in Dimension
    }
    actual = {(label.case_id, label.dimension) for label in plan.labels}
    if actual != expected or len(plan.labels) != len(expected):
        raise EvaluationError("Judge scorecards require complete original blind labels")


def prepare_judges(prepared: PreparedEvaluation, directory: Path) -> PreparedEvaluation:
    """Grade an existing archive using its original prompts, prices, and labels.

    Args:
        prepared: Earlier measured layers and artifacts.
        directory: Judge directory containing plan.json and run.json.
    Returns:
        Offline graders plus calibration, individual outcomes, and source metadata.
    Raises:
        EvaluationError: Cohort, labels, or outcome inventory is incomplete.
    """
    plan = JudgePlan.model_validate_json((directory / "plan.json").read_bytes())
    run = JudgeRun.model_validate_json((directory / "run.json").read_bytes())
    validate_cohort(plan.corpus, plan.config)
    _check_labels(plan)
    summary = summarize(plan, run)
    graders = dict(prepared.graders)
    original = graders.get(3, distinct.grade)
    graders[3] = lambda layer: _identification(original(layer), summary, plan, run)
    graders[4] = lambda layer: _rubric(layer, summary, plan, run)
    manifest = {
        "plan_digest": plan.digest,
        "corpus_digest": plan.corpus.digest,
        "config": plan.config.model_dump(mode="json"),
        "models": {r: m.model_dump(mode="json") for r, m in plan.models.items()},
        "sources": sorted(
            {(c.source_run_id, c.source_git_sha, c.generation_prompt) for c in plan.corpus.cases}
        ),
        "prompts": {j.prompt_file: j.prompt for j in plan.jobs},
    }
    artifacts = prepared.artifacts | {
        "judge_summary.json": summary.model_dump_json(indent=2) + "\n",
        "judge_run.json": run.model_dump_json(indent=2) + "\n",
        "judge_manifest.json": json.dumps(manifest, indent=2) + "\n",
    }
    return PreparedEvaluation(graders, artifacts)
