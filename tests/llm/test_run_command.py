"""Specify offline product command persistence and cache-miss behavior.

Owns: Public CLI outcome before any live provider approval.
Does not own: Generating analyst responses in this command test.
"""

import csv
import json
from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.settings import load_settings
from tests.fixtures.ranking import transaction


def test_replay_writes_failed_page_without_constructing_a_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "project"
    copytree(source / "config", root / "config")
    (root / "prompts").mkdir()
    prompt_file = load_settings(root / "config").analyst.prompt_file
    (root / "prompts" / prompt_file).write_text("Fixture instructions.")
    (root / "data").mkdir()
    row = transaction(sector="Healthcare Services").model_dump() | {
        "sub_sector": "Healthcare Services"
    }
    with (root / "data/ma_transactions_500.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    monkeypatch.setattr("acquirer_engine.cli._git_state", lambda _: ("a" * 40, False))

    def no_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("Replay must not construct a provider client")

    monkeypatch.setattr("acquirer_engine.run_command.create_client", no_client)
    result = CliRunner().invoke(build_app(), ["run", "--project", str(root), "--replay"])
    assert result.exit_code == 1, result.output
    report = json.loads(next((root / "runs").glob("*/run.json")).read_text())
    assert report["mode"] == "replay" and report["pages"][0]["status"] == "failed"
    assert "Replay cache missing" in report["pages"][0]["errors"][0]
    assert report["calls"] == []


def test_cli_exposes_explicit_tools_and_reviewer_ablation_flags() -> None:
    result = CliRunner().invoke(build_app(), ["run", "--help"])
    assert result.exit_code == 0
    assert "--no-tools" in result.output
    assert "--no-reviewer" in result.output
