"""Exercise target and feedback selection through a network-free command.

Owns: CLI precedence, excluded buyers, and snapshot audit information.
Does not own: Generating new rationale in a cache-miss run.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from tests.fixtures.project import write_project
from tests.fixtures.ranking import transaction


def test_run_uses_target_flags_and_persisted_feedback_before_selecting_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project(
        tmp_path,
        (
            transaction(1, acquirer="Blocked"),
            transaction(2, acquirer="Similar"),
            transaction(3, acquirer="Unrelated", sector="Technology"),
        ),
    )
    monkeypatch.setattr("acquirer_engine.replay.git_state", lambda _: ("a" * 40, False))
    path = tmp_path / "target.yaml"
    path.write_text("sector: Services\ndeal_size_mm: 100\n")
    runner = CliRunner()
    flagged = runner.invoke(
        build_app(), ["flag", "Blocked", "--reason", "conflict", "--project", str(tmp_path)]
    )
    assert flagged.exit_code == 0, flagged.output
    arguments = ["run", "--replay", "--project", str(tmp_path), "--target", str(path)]
    arguments += ["--ev", "300", "--margin", "25", "--no-tools", "--no-reviewer"]
    result = runner.invoke(build_app(), arguments)
    assert result.exit_code == 1, result.output
    files = list((tmp_path / "runs").glob("*/snapshot.json"))
    assert len(files) == 1, result.output
    snapshot = json.loads(files[0].read_text())
    assert snapshot["feedback"]["flags"][0]["acquirer"] == "Blocked"
    assert {p["ranking"]["acquirer"] for p in snapshot["packs"]} == {"Similar", "Unrelated"}
    for pack in snapshot["packs"]:
        assert pack["target"]["deal_size_mm"] == 300
        assert pack["target"]["ebitda_margin_pct"] == 25
    similar = next(p for p in snapshot["packs"] if p["ranking"]["acquirer"] == "Similar")
    assert any(s["metric"] == "feedback_multiplier" for s in similar["statistics"])
