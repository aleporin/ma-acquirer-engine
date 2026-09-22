"""Specify persisted user exclusions and auditable similarity penalties.

Owns: Atomic state, canonical identity, and product ranking adjustments.
Does not own: Learning scoring weights or changing evaluation baselines.
"""

from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.errors import DataError
from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.feedback import ranking, state
from acquirer_engine.feedback import state as module
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.ranking.target import assignment_target
from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction


def test_state_canonicalizes_names_and_preserves_other_flags(tmp_path: Path) -> None:
    path = tmp_path / "feedback.json"
    module.save_flag(path, " buyer a ", "conflict", {"Buyer A", "Buyer B"})
    module.save_flag(path, "Buyer B", "not a fit", {"Buyer A", "Buyer B"})
    module.save_flag(path, "BUYER A", "updated reason", {"Buyer A", "Buyer B"})
    state = module.load_feedback(path)
    assert [(f.acquirer, f.reason) for f in state.flags] == [
        ("Buyer A", "updated reason"),
        ("Buyer B", "not a fit"),
    ]
    before = path.read_bytes()
    with pytest.raises(DataError, match="Unknown"):
        module.save_flag(path, "not in dataset", "reason", {"Buyer A", "Buyer B"})
    assert path.read_bytes() == before


def test_corrupt_feedback_is_never_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "feedback.json"
    path.write_text("broken state")
    with pytest.raises(DataError, match="feedback"):
        module.save_flag(path, "Buyer A", "reason", {"Buyer A"})
    assert path.read_text() == "broken state"


def test_flagged_buyer_excluded_and_similar_profile_downweighted(settings: Settings) -> None:
    rows = (
        transaction(1, acquirer="Blocked", sector="Healthcare Services"),
        transaction(2, acquirer="Similar", sector="Healthcare Services"),
        transaction(3, acquirer="Unrelated", sector="Technology"),
    )
    fitted = fit_features(rows, settings.scoring, reference_year=2024)
    target = assignment_target(rows, settings.scoring)
    original = rank_acquirers(fitted, target, settings.scoring)
    flags = state.FeedbackState(flags=(state.BuyerFlag(acquirer="Blocked", reason="conflict"),))
    adjusted = ranking.apply_feedback(original, fitted, flags, 0.2, settings.scoring)
    scores = {item.acquirer: item.score for item in original}
    assert {item.acquirer for item in adjusted} == {"Similar", "Unrelated"}
    by_name = {item.acquirer: item for item in adjusted}
    assert by_name["Similar"].score == pytest.approx(scores["Similar"] * 0.8)
    assert by_name["Unrelated"].score == scores["Unrelated"]
    assert (
        ranking.apply_feedback(original, fitted, state.FeedbackState(), 0.2, settings.scoring)
        == original
    )


def test_flag_command_persists_to_project_state(tmp_path: Path) -> None:
    import csv

    root = Path(__file__).resolve().parents[2]
    copytree(root / "config", tmp_path / "config")
    (tmp_path / "data").mkdir()
    row = transaction().model_dump() | {"sub_sector": "Services"}
    with (tmp_path / "data/ma_transactions_500.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    result = CliRunner().invoke(
        build_app(), ["flag", "Buyer A", "--reason", "conflict", "--project", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert '"acquirer": "Buyer A"' in (tmp_path / "state/feedback.json").read_text()
