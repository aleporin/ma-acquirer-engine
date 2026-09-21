"""Exercise the offline harness and its serialized scorecards.

Owns: Stub status, provenance, failure propagation, and artifact contracts.
Does not own: Actual quality metrics or provider calls.
"""

import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import LayerSpec
from evals.harness import evaluate
from evals.scorecard import LayerResult, RunInfo, Scorecard, read_scorecard, write_scorecard


def test_all_layers_report_not_implemented_without_metrics(deps: Deps, run: RunInfo) -> None:
    card = evaluate(deps, run, deps.settings.evaluation.offline_layers)
    assert [layer.id for layer in card.layers] == list(range(7))
    assert {layer.status for layer in card.layers} == {"not_implemented"}
    assert all(not layer.metrics for layer in card.layers)
    assert not card.layers[4].selected
    assert card.models == deps.settings.models
    assert card.run == run


def test_ci_selection_keeps_full_baseline_visible(deps: Deps, run: RunInfo) -> None:
    card = evaluate(deps, run, deps.settings.evaluation.ci_layers)
    assert [layer.id for layer in card.layers if layer.selected] == [0, 1, 2]
    assert len(card.layers) == 7


def test_invalid_selection_fails(deps: Deps, run: RunInfo) -> None:
    with pytest.raises(EvaluationError, match="selection"):
        evaluate(deps, run, [0, 4])


def test_grader_failure_propagates_without_a_success_card(deps: Deps, run: RunInfo) -> None:
    def broken(layer: LayerSpec) -> LayerResult:
        raise EvaluationError("grader failed")

    with pytest.raises(EvaluationError, match="grader failed"):
        evaluate(deps, run, [0], graders={0: broken})


def test_writes_valid_json_and_markdown_in_revision_directory(
    deps: Deps, run: RunInfo, tmp_path: Path
) -> None:
    card = evaluate(deps, run, deps.settings.evaluation.offline_layers)
    path = write_scorecard(card, tmp_path)
    assert path == tmp_path / f"p0-{run.git_sha}" / "scorecard.json"
    assert read_scorecard(path) == card
    summary = path.with_name("summary.md").read_text()
    assert "not_implemented" in summary
    assert run.git_sha in summary
    assert len(json.loads(path.read_text())["layers"]) == 7


def test_existing_baseline_cannot_be_silently_overwritten(
    deps: Deps, run: RunInfo, tmp_path: Path
) -> None:
    card = evaluate(deps, run, [0])
    write_scorecard(card, tmp_path)
    with pytest.raises(EvaluationError, match="already exists"):
        write_scorecard(card, tmp_path)


def test_not_implemented_cannot_claim_metrics(deps: Deps, run: RunInfo) -> None:
    data = evaluate(deps, run, [0]).model_dump(mode="json")
    data["layers"][0]["metrics"] = {"accuracy": {"value": 1, "direction": "higher"}}
    with pytest.raises(ValidationError):
        Scorecard.model_validate(data)


def test_invalid_scorecard_is_a_typed_error(tmp_path: Path) -> None:
    path = tmp_path / "scorecard.json"
    path.write_text("{}")
    with pytest.raises(EvaluationError):
        read_scorecard(path)


def test_network_guard_rejects_connection_attempts() -> None:
    with pytest.raises(AssertionError, match="Network is forbidden"):
        socket.create_connection(("example.invalid", 443))
