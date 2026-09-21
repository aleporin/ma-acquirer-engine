"""Add recorded analyst observations to offline evaluation.

Owns: Run-artifact provenance checks, claim rates, and grader composition.
Does not own: Provider execution or treating replay as a live measurement.
"""

import json
from functools import partial
from pathlib import Path

from pydantic import ValidationError

from acquirer_engine.errors import EvaluationError
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.settings import Settings
from evals.graders import distinct, ops, stability
from evals.harness import Grader
from evals.phase1 import PreparedEvaluation
from evals.scorecard import LayerResult, Metric


def _load_runs(paths: list[Path], settings: Settings) -> list[AnalystRun]:
    try:
        runs = [
            AnalystRun.model_validate_json(path.read_text(), context=settings.evidence.validation)
            for path in paths
        ]
    except (OSError, ValueError, ValidationError) as error:
        raise EvaluationError("Invalid analyst run artifact") from error
    if len({run.run_id for run in runs}) != len(runs):
        raise EvaluationError("Duplicate analyst run identity")
    if len({(run.git_sha, run.prompt_version) for run in runs}) > 1:
        raise EvaluationError("Analyst stability requires matching source and prompt versions")
    if any(call.mode != run.mode for run in runs for call in run.calls):
        raise EvaluationError("Run mode conflicts with response usage mode")
    return runs


def _claims(baseline: LayerResult, runs: list[AnalystRun]) -> LayerResult:
    metrics = dict(baseline.metrics)
    for mode in sorted({run.mode for run in runs}):
        pages = [p for run in runs if run.mode == mode for p in run.pages]
        count = sum(p.claims_total for p in pages)
        if count:
            metrics[f"{mode}_first_pass_claim_rate"] = Metric(
                value=sum(p.claims_verified for p in pages) / count, direction="higher"
            )
        if pages:
            metrics[f"{mode}_first_pass_page_rate"] = Metric(
                value=sum(p.status == "verified" for p in pages) / len(pages), direction="higher"
            )
        metrics[f"{mode}_parsed_claims"] = Metric(value=count, direction="higher")
        metrics[f"{mode}_pages_without_parsed_claims"] = Metric(
            value=sum(p.claims_total == 0 for p in pages), direction="lower"
        )
    return baseline.model_copy(update={"metrics": metrics})


def prepare_phase3(
    prepared: PreparedEvaluation, paths: list[Path], settings: Settings
) -> PreparedEvaluation:
    """Measure saved runs without ever invoking a provider.

    Args:
        prepared: Existing unit, ranking, and fixture measurements.
        paths: Explicit run.json observations; absent means live metrics remain unmeasured.
        settings: Shared validation and measurement policy.
    Returns:
        Combined graders with a portable copy of the observed run artifacts.
    Raises:
        EvaluationError: Observations are malformed, duplicated, or incompatible.
    """
    if not paths:
        return prepared
    runs = _load_runs(paths, settings)
    graders: dict[int, Grader] = {
        2: lambda layer: _claims(prepared.graders[2](layer), runs),
        3: partial(distinct.grade, runs=runs, config=settings.analyst),
        5: lambda layer: stability.with_validation(
            prepared.graders[5](layer), runs, settings.analyst
        ),
        6: partial(
            ops.grade, runs=runs, config=settings.analyst, expected_pages=settings.scoring.top_k
        ),
    }
    observations = {
        "scope": "recorded_runs; replay does not measure live stochasticity or spend",
        "runs": [run.model_dump(mode="json") for run in runs],
    }
    return PreparedEvaluation(
        prepared.graders | graders,
        prepared.artifacts
        | {"analyst_observations.json": json.dumps(observations, indent=2) + "\n"},
    )
