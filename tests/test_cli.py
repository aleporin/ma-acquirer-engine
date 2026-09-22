"""Exercise commands through the public CLI.

Owns: Offline command behavior, artifact paths, and exit statuses.
Does not own: Model integration or Git's revision algorithms.
"""

import csv
import json
from pathlib import Path
from shutil import copytree

import pytest
import yaml
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from evals.graders.unit import UnitReport
from evals.scorecard import read_scorecard
from tests.fixtures.ranking import transaction


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    source = Path(__file__).resolve().parents[1] / "config"
    copytree(source, root / "config")
    path = root / "config/eval.yaml"
    config = yaml.safe_load(path.read_text())
    config["phase"] = "p0"
    config["offline_layers"] = [0, 1, 2, 3, 5, 6]
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr("acquirer_engine.run_history.git_state", lambda root: ("a" * 40, False))
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


@pytest.mark.parametrize("arguments", [["eval", "--fresh"]])
def test_unavailable_commands_fail_without_provider_access(arguments: list[str]) -> None:
    result = CliRunner().invoke(build_app(), arguments)
    assert result.exit_code == 2
    assert "not implemented" in result.output or "offline" in result.output


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


@pytest.mark.parametrize("phase", ["p1", "p2"])
def test_measured_bundle_reports_uniform_conviction_as_a_diagnostic(
    project: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    config_path = project / "config/eval.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["phase"] = phase
    if phase == "p2":
        copytree(Path(__file__).resolve().parents[1] / "evals/fixtures", project / "evals/fixtures")
    config["backtest"]["bootstrap_samples"] = 50
    config_path.write_text(yaml.safe_dump(config))
    rows = [
        transaction(1, sector="Healthcare Services"),
        transaction(2, deal_year=2022, sector="Healthcare Services"),
    ]
    (project / "data").mkdir()
    values = [row.model_dump() | {"sub_sector": row.sector} for row in rows]
    with (project / "data/ma_transactions_500.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
    monkeypatch.setattr(
        "evals.command.run_tests",
        lambda *args, **kwargs: UnitReport(4, 4, 0, 0, 0.8, 0),
        raising=False,
    )
    result = CliRunner().invoke(build_app(), ["eval", "--project", str(project)])
    assert result.exit_code == 0, result.output
    path = next((project / "evals/results").glob("*/scorecard.json"))
    card = read_scorecard(path)
    assert card.layers[0].metrics["coverage"].value == 0.8
    assert card.layers[1].status == "passed"
    assert card.layers[5].status == "passed"
    assert card.layers[5].metrics["conviction_diversity_target_met"].value == 0
    assert path.with_name("top10.json").exists()

    if phase == "p2":
        assert card.layers[2].status == "passed"
        assert path.with_name("groundedness.json").exists()
