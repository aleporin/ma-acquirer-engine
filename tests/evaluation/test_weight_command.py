"""Protect offline defaults and frozen proposal inputs at the CLI boundary.

Owns: Explicit live opt-in, snapshot integrity, and configuration mismatch rejection.
Does not own: Provider integration or ranking quality claims.
"""

from importlib import import_module
from pathlib import Path

import pytest
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import Settings
from evals.ranking.packet import build_packet, packet_digest
from evals.ranking.proposals import ProposalRun, ProposalSnapshot
from tests.evaluation.test_weighting import module_and_policy
from tests.fixtures.ranking import transaction


def test_proposal_command_defaults_to_offline_and_requires_saved_source() -> None:
    result = CliRunner().invoke(build_app(), ["propose-weights"])
    assert result.exit_code == 1
    assert "Replay requires --source" in result.output


def test_live_proposal_cannot_silently_reuse_a_source() -> None:
    result = CliRunner().invoke(build_app(), ["propose-weights", "--fresh", "--source", "."])
    assert result.exit_code == 1
    assert "--fresh cannot use --source" in result.output


def test_experiment_rejects_tampered_or_mismatched_inputs(
    settings: Settings, tmp_path: Path
) -> None:
    module = import_module("evals.ranking.weight_command")
    weighting, policy = module_and_policy()
    rows = (transaction(1, deal_year=2018),)
    packet = build_packet(rows, policy, settings.scoring)
    snapshot = ProposalSnapshot(
        settings=settings,
        policy=policy,
        packet=packet,
        packet_sha256=packet_digest(packet),
        prompt="propose",
        git_sha="a" * 40,
        source_dirty=False,
    )
    encoded = snapshot.model_dump_json(indent=2) + "\n"
    (tmp_path / "input.json").write_text(encoded)
    candidate = weighting.shared_candidate(settings.scoring).model_copy(update={"name": "same"})
    run = ProposalRun(
        run_id=tmp_path.name,
        git_sha=snapshot.git_sha,
        source_dirty=False,
        packet_sha256=snapshot.packet_sha256,
        snapshot_sha256=module.digest(encoded),
        candidates=[candidate],
    )
    (tmp_path / "proposal.json").write_text(run.model_dump_json())
    assert module.checked_proposal(tmp_path, rows, settings, policy) == (snapshot, run)
    changed = settings.model_copy(
        update={"scoring": settings.scoring.model_copy(update={"prior_strength": 99})}
    )
    with pytest.raises(EvaluationError, match="configuration"):
        module.checked_proposal(tmp_path, rows, changed, policy)
    (tmp_path / "input.json").write_text(encoded.replace('"propose"', '"different"'))
    with pytest.raises(EvaluationError, match="digest"):
        module.checked_proposal(tmp_path, rows, settings, policy)
