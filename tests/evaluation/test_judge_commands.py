"""Specify explicit paid execution and useful credential-free planning.

Owns: CLI safety, complete calibration cohorts, and offline cost planning.
Does not own: Live calls, secret loading, or human ratings.
"""

import json
from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from evals.judges.labels import export_packet
from evals.judges.prepare import validate_cohort
from tests.evaluation.test_judge_runner import plan_for_test


def fixture_project(tmp_path: Path, deps: Deps) -> Path:
    source = Path(__file__).resolve().parents[2]
    copytree(source / "config", tmp_path / "config")
    copytree(source / "prompts/judges", tmp_path / "prompts/judges")
    plan = plan_for_test(deps)
    (tmp_path / "evals/cases").mkdir(parents=True)
    (tmp_path / "evals/cases/p5-calibration.json").write_text(plan.corpus.model_dump_json())
    export_packet(plan.corpus, tmp_path / "evals/labels")
    return tmp_path


def test_default_judge_command_plans_without_keys_or_human_labels(
    tmp_path: Path, deps: Deps
) -> None:
    root = fixture_project(tmp_path, deps)
    result = CliRunner().invoke(build_app(), ["eval-judges", "--project", str(root)])
    assert result.exit_code == 0, result.output
    estimate = json.loads(result.output)
    assert estimate["jobs"] == 12 and estimate["unique_requests"] == 12
    assert estimate["conservative_usd"] > 0 and estimate["max_run_usd"] > 0
    assert not (root / "runs").exists()


def test_fresh_judging_requires_completed_blind_labels_before_clients(
    tmp_path: Path, deps: Deps
) -> None:
    root = fixture_project(tmp_path, deps)
    result = CliRunner().invoke(build_app(), ["eval-judges", "--project", str(root), "--fresh"])
    assert result.exit_code == 1 and "complete" in result.output
    assert not (root / "runs").exists()


def test_paid_cohort_requires_two_matched_ten_buyer_runs(deps: Deps) -> None:
    plan = plan_for_test(deps)
    with pytest.raises(EvaluationError, match="calibration"):
        validate_cohort(plan.corpus, plan.config)


def test_fresh_and_replay_are_mutually_exclusive(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        build_app(), ["eval-judges", "--fresh", "--replay-from", str(tmp_path)]
    )
    assert result.exit_code == 2 and "mutually exclusive" in result.output
