"""Require trustworthy provenance for analyst evaluation artifacts.

Owns: Duplicate-run rejection and composition with earlier phase measurements.
Does not own: Producing or purchasing model responses.
"""

from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import LayerSpec, Settings
from evals.graders import ops
from evals.phase1 import PreparedEvaluation
from evals.phase3 import prepare_phase3
from evals.scorecard import LayerResult
from tests.evals.test_analyst_metrics import observation


def test_analyst_artifacts_add_claim_metrics_without_replacing_fixture_metrics(
    deps: Deps, tmp_path: Path
) -> None:
    run = observation(deps.settings)
    path = tmp_path / "run.json"
    path.write_text(run.model_dump_json())
    baseline = PreparedEvaluation(
        {
            2: lambda layer: LayerResult(id=2, name=layer.name, selected=True, status="passed"),
            5: lambda layer: LayerResult(id=5, name=layer.name, selected=True, status="failed"),
        },
        {},
    )
    combined = prepare_phase3(baseline, [path], deps.settings)
    result = combined.graders[2](LayerSpec(id=2, name="groundedness"))
    assert result.metrics["replay_first_pass_claim_rate"].value == 1
    assert result.metrics["replay_first_pass_page_rate"].value == 1
    assert "analyst_observations.json" in combined.artifacts
    with pytest.raises(EvaluationError, match="Duplicate"):
        prepare_phase3(baseline, [path, path], deps.settings)


def test_live_gate_requires_the_configured_number_of_pages(settings: Settings) -> None:
    run = observation(settings).model_copy(update={"mode": "live"})
    call = run.calls[0].model_copy(update={"mode": "live", "cost_usd": 0.001})
    run = run.model_copy(update={"calls": [call]})
    result = ops.grade(
        LayerSpec(id=6, name="operations"),
        [run],
        settings.analyst,
        expected_pages=settings.scoring.top_k,
    )
    assert result.metrics["live_gate_met"].value == 0
    assert result.status == "failed"


def test_repaired_success_does_not_rewrite_first_pass_metrics(deps: Deps, tmp_path: Path) -> None:
    run = observation(deps.settings)
    raw = run.model_dump(mode="json")
    raw["pages"][0]["attempts"] = [
        dict(
            stage="analyst",
            status="failed",
            errors=["wrong value"],
            claims_total=4,
            claims_verified=3,
        ),
        dict(stage="repair", status="verified", errors=[], claims_total=4, claims_verified=4),
    ]
    import json

    path = tmp_path / "run.json"
    path.write_text(json.dumps(raw))
    baseline = PreparedEvaluation(
        {2: lambda layer: LayerResult(id=2, name=layer.name, selected=True, status="passed")}, {}
    )
    combined = prepare_phase3(baseline, [path], deps.settings)
    result = combined.graders[2](LayerSpec(id=2, name="groundedness"))
    assert result.metrics["replay_first_pass_claim_rate"].value == 0.75
    assert result.metrics["replay_first_pass_page_rate"].value == 0
    assert result.metrics["replay_post_repair_claim_rate"].value == 1
    assert result.metrics["replay_post_repair_page_rate"].value == 1
