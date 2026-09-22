"""Keep ablation failures distinct from baseline quality and review effects.

Owns: Routing metric arithmetic and phase-specific observation partitioning.
Does not own: Purchasing model generations or judging banker tone.
"""

from importlib import import_module
from pathlib import Path

from acquirer_engine.deps import Deps
from acquirer_engine.settings import LayerSpec
from evals.phase1 import PreparedEvaluation
from evals.scorecard import LayerResult
from tests.fixtures.observations import observation


def test_ablation_failures_do_not_reduce_full_pipeline_page_rate(
    deps: Deps, tmp_path: Path
) -> None:
    import json

    paths = []
    for i, (tools, reviewer) in enumerate([(True, True), (False, True), (True, False)]):
        raw = observation(deps.settings, i).model_dump(mode="json")
        raw.update(tools_enabled=tools, reviewer_enabled=reviewer)
        if not tools:
            for page in raw["pages"]:
                page.update(
                    status="failed",
                    rationale=None,
                    errors=["valuation_context: no comps"],
                    tools=[],
                    claims_total=4,
                    claims_verified=2,
                )
        path = tmp_path / f"run{i}.json"
        path.write_text(json.dumps(raw))
        paths.append(path)
    prepared = PreparedEvaluation(
        {
            i: lambda layer: LayerResult(
                id=layer.id, name=layer.name, selected=True, status="passed"
            )
            for i in (2, 5)
        },
        {},
    )
    result = import_module("evals.phase4").prepare_phase4(prepared, paths, deps.settings)
    claims = result.graders[2](LayerSpec(id=2, name="claims")).metrics
    assert claims["replay_post_review_page_rate"].value == 1
    metrics = result.graders[6](LayerSpec(id=6, name="ops")).metrics
    assert metrics["replay_tools_disabled_validation_failure_rate"].value == 1
    assert metrics["replay_reviewer_disabled_runs"].value == 1
    assert "live_gate_met" not in metrics
