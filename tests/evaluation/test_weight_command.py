"""Protect offline defaults and frozen proposal inputs at the CLI boundary.

Owns: Explicit live opt-in, snapshot integrity, and configuration mismatch rejection.
Does not own: Provider integration or ranking quality claims.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import Settings
from evals.ranking.packet import build_packet, packet_digest
from evals.ranking.proposals import ProposalRun, ProposalSnapshot
from tests.evaluation.test_weighting import module_and_policy
from tests.fixtures.ranking import transaction
from tests.ranking.test_type_weights import type_policy


@pytest.mark.asyncio
async def test_a_replayed_proposal_can_be_replayed_again(
    deps: Deps,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("evals.ranking.weight_command")
    weighting, policy = module_and_policy()
    candidate = weighting.shared_candidate(deps.settings.scoring).model_copy(
        update={"name": "same"}
    )
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"candidates": [candidate.model_dump()]})
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=80),
        )

    @asynccontextmanager
    async def resources(deps: Deps, *, replay: bool) -> AsyncIterator[tuple[Model | None, None]]:
        yield (None if replay else FunctionModel(respond)), None

    monkeypatch.setattr(module, "model_resources", resources)
    snapshot = ProposalSnapshot(
        settings=deps.settings,
        policy=policy,
        packet={},
        packet_sha256=packet_digest({}),
        prompt="propose",
        git_sha="a" * 40,
        source_dirty=False,
    )
    first = await module._request(snapshot, tmp_path / "first", deps, None)
    second = await module._request(snapshot, tmp_path / "second", deps, tmp_path / "first")
    third = await module._request(snapshot, tmp_path / "third", deps, tmp_path / "second")
    assert not first.errors and not second.errors and not third.errors
    assert first.candidates == second.candidates == third.candidates
    assert calls == 1
    assert all(call.cost_usd == 0 for run in (second, third) for call in run.calls)
    assert first.git_sha == second.git_sha == third.git_sha == snapshot.git_sha


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
    adopted = settings.model_copy(update={"scoring": type_policy(settings)})
    assert module.checked_proposal(tmp_path, rows, adopted, policy) == (snapshot, run)
    (tmp_path / "input.json").write_text(encoded.replace('"propose"', '"different"'))
    with pytest.raises(EvaluationError, match="digest"):
        module.checked_proposal(tmp_path, rows, settings, policy)
