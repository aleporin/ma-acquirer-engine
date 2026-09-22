"""Require trustworthy provenance for analyst evaluation artifacts.

Owns: Duplicate-run rejection and composition with earlier phase measurements.
Does not own: Producing or purchasing model responses.
"""

from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import LayerSpec, Settings
from evals.analyst import prepare_analyst
from evals.graders import ops
from evals.harness import PreparedEvaluation
from evals.scorecard import LayerResult
from tests.fixtures.observations import observation


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
    combined = prepare_analyst(baseline, [path], deps.settings)
    result = combined.graders[2](LayerSpec(id=2, name="groundedness"))
    assert result.metrics["replay_first_pass_claim_rate"].value == 1
    assert result.metrics["replay_first_pass_page_rate"].value == 1
    assert "analyst_observations.json" in combined.artifacts
    with pytest.raises(EvaluationError, match="Duplicate"):
        prepare_analyst(baseline, [path, path], deps.settings)


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
    raw["pages"] = raw["pages"][:1]
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
    combined = prepare_analyst(baseline, [path], deps.settings)
    result = combined.graders[2](LayerSpec(id=2, name="groundedness"))
    assert result.metrics["replay_first_pass_claim_rate"].value == 0.75
    assert result.metrics["replay_first_pass_page_rate"].value == 0
    assert result.metrics["replay_post_repair_claim_rate"].value == 1
    assert result.metrics["replay_post_repair_page_rate"].value == 1


def test_reviewer_failure_cannot_rewrite_post_repair_claim_rate(deps: Deps, tmp_path: Path) -> None:
    import json

    raw = observation(deps.settings).model_dump(mode="json")
    raw["pages"] = raw["pages"][:1]
    raw["pages"][0].update(
        status="failed",
        rationale=None,
        claims_total=4,
        claims_verified=3,
        errors=["revision introduced a wrong number"],
        attempts=[
            dict(stage="analyst", status="verified", errors=[], claims_total=4, claims_verified=4),
            dict(
                stage="revision",
                status="failed",
                errors=["wrong number"],
                claims_total=4,
                claims_verified=3,
            ),
        ],
    )
    path = tmp_path / "run.json"
    path.write_text(json.dumps(raw))
    baseline = PreparedEvaluation(
        {2: lambda layer: LayerResult(id=2, name=layer.name, selected=True, status="passed")}, {}
    )
    metrics = (
        prepare_analyst(baseline, [path], deps.settings)
        .graders[2](LayerSpec(id=2, name="groundedness"))
        .metrics
    )
    assert metrics["replay_post_repair_claim_rate"].value == 1
    assert metrics["replay_post_review_claim_rate"].value == 0.75
