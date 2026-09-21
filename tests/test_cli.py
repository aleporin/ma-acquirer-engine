"""Exercise commands through the public CLI.

Owns: Offline command behavior, artifact paths, and exit statuses.
Does not own: Model integration or Git's revision algorithms.
"""

import json
from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from evals.scorecard import read_scorecard


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    source = Path(__file__).resolve().parents[1] / "config"
    copytree(source, root / "config")
    monkeypatch.setattr("acquirer_engine.cli._git_state", lambda root: ("a" * 40, False))
    return root


def test_help_lists_phase_zero_commands() -> None:
    result = CliRunner().invoke(build_app(), ["--help"])
    assert result.exit_code == 0
    assert "eval-diff" in result.output
    assert "eval-judges" in result.output


def test_eval_writes_all_seven_stub_results(project: Path) -> None:
    result = CliRunner().invoke(build_app(), ["eval", "--project", str(project), "--replay"])
    assert result.exit_code == 0, result.output
    path = next((project / "evals/results").glob("*/scorecard.json"))
    card = read_scorecard(path)
    assert {layer.status for layer in card.layers} == {"not_implemented"}
    assert not card.run.source_dirty
    assert (project / f"runs/{card.run.run_id}/log.jsonl").is_file()


def test_ci_selects_only_layers_zero_through_two(project: Path) -> None:
    result = CliRunner().invoke(build_app(), ["eval", "--project", str(project), "--ci"])
    assert result.exit_code == 0, result.output
    path = next((project / "evals/results").glob("*/scorecard.json"))
    assert read_scorecard(path).requested_layers == [0, 1, 2]


@pytest.mark.parametrize(
    "arguments", [["run"], ["run", "--fresh"], ["eval-judges"], ["eval", "--fresh"]]
)
def test_unavailable_commands_fail_without_provider_access(arguments: list[str]) -> None:
    result = CliRunner().invoke(build_app(), arguments)
    assert result.exit_code == 2
    assert "Phase 0" in result.output


def test_invalid_configuration_has_no_traceback(project: Path) -> None:
    (project / "config/models.yaml").unlink()
    result = CliRunner().invoke(build_app(), ["eval", "--project", str(project)])
    assert result.exit_code == 1
    assert "models.yaml" in result.output
    assert "Traceback" not in result.output


def test_eval_diff_reports_regression_with_nonzero_exit(project: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(build_app(), ["eval", "--project", str(project)]).exit_code == 0
    path = next((project / "evals/results").glob("*/scorecard.json"))
    before = json.loads(path.read_text())
    before["layers"][0]["status"] = "passed"
    old = project / "before.json"
    old.write_text(json.dumps(before))
    result = runner.invoke(build_app(), ["eval-diff", str(old), str(path)])
    assert result.exit_code == 1
    assert "passed -> not_implemented" in result.output


def test_second_eval_preserves_existing_baseline(project: Path) -> None:
    runner = CliRunner()
    arguments = ["eval", "--project", str(project)]
    assert runner.invoke(build_app(), arguments).exit_code == 0
    path = next((project / "evals/results").glob("*/scorecard.json"))
    original = path.read_bytes()
    result = runner.invoke(build_app(), arguments)
    assert result.exit_code == 1
    assert path.read_bytes() == original
