"""Recover recorded weight responses without another provider request.

Owns: Failed-run replay, immutable originals, and normalized-name boundaries.
Does not own: Live provider behavior or candidate selection.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.factory import build_services
from evals.ranking import weight_command
from evals.ranking.packet import packet_digest
from evals.ranking.proposals import ProposalResponse, ProposalRun, ProposalSet, ProposalSnapshot
from tests.evaluation.test_weighting import module_and_policy


@pytest.mark.asyncio
@pytest.mark.parametrize("names", [("Shared",), ("Size Fit", "size_fit")])
async def test_normalized_names_cannot_shadow_controls_or_collide(
    deps: Deps, tmp_path: Path, names: tuple[str, ...]
) -> None:
    from evals.ranking.proposals import request_proposals

    weighting, policy = module_and_policy()
    candidate = weighting.shared_candidate(deps.settings.scoring).model_dump()
    calls = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"candidates": [dict(candidate, name=name) for name in names]},
                )
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=80),
        )

    services = build_services(deps, FunctionModel(respond), (), tmp_path, "propose", mode="test")
    with pytest.raises(UnexpectedModelBehavior):
        await request_proposals({}, deps.with_runtime(services), "propose", policy)
    assert len(calls) == 1


def install_proposal_fixture(deps: Deps, monkeypatch: pytest.MonkeyPatch) -> list[ModelMessage]:
    """Install a single offline provider and frozen inputs for the public CLI."""
    weighting, policy = module_and_policy()
    candidate = weighting.shared_candidate(deps.settings.scoring).model_dump()
    candidate["name"] = "Size-Scale Emphasis"
    calls: list[ModelMessage] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.extend(messages)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"candidates": [candidate]})],
            usage=RequestUsage(input_tokens=100, output_tokens=80),
        )

    @asynccontextmanager
    async def resources(deps: Deps, *, replay: bool) -> AsyncIterator[tuple[Model | None, None]]:
        yield (None if replay else FunctionModel(respond)), None

    snapshot = ProposalSnapshot(
        settings=deps.settings,
        policy=policy,
        packet={},
        packet_sha256=packet_digest({}),
        prompt="propose",
        git_sha="a" * 40,
        source_dirty=False,
    )
    monkeypatch.setattr(weight_command, "model_resources", resources)
    monkeypatch.setattr(weight_command, "_fresh_snapshot", lambda root: snapshot)
    return calls


def test_failed_proposal_replays_through_fixed_validation_without_another_call(
    deps: Deps, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_proposal_fixture(deps, monkeypatch)
    original = ProposalResponse.hypotheses

    def reject(response: ProposalResponse) -> ProposalSet:
        raise EvaluationError("Old parser rejects display names")

    monkeypatch.setattr(ProposalResponse, "hypotheses", reject)
    runner = CliRunner()
    first = runner.invoke(build_app(), ["propose-weights", "--fresh", "--project", str(tmp_path)])
    assert first.exit_code == 1
    source = next((tmp_path / "runs/weight-proposals").iterdir())
    saved = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    call_count = len(calls)
    with pytest.raises(EvaluationError, match="failed"):
        weight_command._load(source)

    monkeypatch.setattr(ProposalResponse, "hypotheses", original)
    result = runner.invoke(
        build_app(), ["propose-weights", "--source", str(source), "--project", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    recovered = next(p for p in source.parent.iterdir() if p != source)
    report = ProposalRun.model_validate_json((recovered / "proposal.json").read_bytes())
    assert not report.errors
    assert report.replay_of == source.name
    assert report.candidates[0].name == "size_scale_emphasis"
    assert len(report.calls) == 1 and report.calls[0].cost_usd == 0
    assert len(calls) == call_count
    assert saved == {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
