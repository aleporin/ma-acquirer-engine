"""Specify offline target comparison and one bounded optional summary request.

Owns: Rank deltas, overlap, saved output, and provider-call count.
Does not own: Evaluating narrative quality or training ranking weights.
"""

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage
from typer.testing import CliRunner

from acquirer_engine.bootstrap import build_services
from acquirer_engine.cli import build_app
from acquirer_engine.deps import Deps
from acquirer_engine.ranking.scorer import RankedAcquirer
from acquirer_engine.ranking.target import TargetProfile
from tests.fixtures.project import write_project
from tests.fixtures.ranking import transaction
from tests.llm.test_run_archive import inputs


def test_comparison_counts_overlap_and_defines_positive_delta_as_improvement(deps: Deps) -> None:
    module = importlib.import_module("acquirer_engine.comparison.ranking")
    target = inputs(deps, "a" * 32).packs[0].target
    base = inputs(deps, "a" * 32).packs[0].ranking
    left = [base.model_copy(update={"acquirer": name}) for name in ("A", "B")]
    right = [base.model_copy(update={"acquirer": name}) for name in ("B", "C")]
    result = module.compare_rankings(target, target, left, right)
    assert result.overlap == ("B",) and result.overlap_fraction == 0.5
    by_name = {item.acquirer: item for item in result.rows}
    assert by_name["B"].rank_a == 2 and by_name["B"].rank_b == 1
    assert by_name["B"].rank_delta == 1
    assert by_name["A"].rank_b is None and by_name["C"].rank_delta is None


def test_compare_command_writes_table_without_a_provider(tmp_path: Path) -> None:
    write_project(
        tmp_path, (transaction(1), transaction(2, acquirer="Buyer B", sector="Technology"))
    )
    for name, sector in (("a", "Services"), ("b", "Technology")):
        (tmp_path / f"{name}.yaml").write_text(f"sector: {sector}\ndeal_size_mm: 200\n")
    result = CliRunner().invoke(
        build_app(),
        ["compare", str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml"), "--project", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    path = next((tmp_path / "runs").glob("*/comparison.json"))
    saved = json.loads(path.read_text())
    assert saved["mode"] == "ranking-only" and saved["calls"] == []
    assert saved["summary"] is None
    assert "rank_delta" in path.read_text()
    assert (path.parent / "comparison.html").exists()


@pytest.mark.asyncio
async def test_summary_uses_one_recorded_call_and_replays_offline(
    deps: Deps, tmp_path: Path, summary_model: tuple[FunctionModel, list[None]]
) -> None:
    module = importlib.import_module("acquirer_engine.comparison.summary")
    ranking = importlib.import_module("acquirer_engine.comparison.ranking")
    snapshot = inputs(deps, "a" * 32)
    target: TargetProfile = snapshot.packs[0].target
    candidate: RankedAcquirer = snapshot.packs[0].ranking
    comparison = ranking.compare_rankings(target, target, [candidate], [candidate])
    policy = module.ComparisonPolicy(
        prompt_file="fixture.md", max_output_tokens=500, summary_chars=1000
    )
    runtime = build_services(
        deps,
        summary_model[0],
        snapshot.history,
        tmp_path / "live",
        "Fixture summary",
        mode="test",
        cache_root=tmp_path / "cache",
    )
    result = await module.summarize(
        comparison, replace(deps, runtime=runtime), "Fixture summary", policy
    )
    replay = build_services(
        deps,
        None,
        snapshot.history,
        tmp_path / "replay",
        "Fixture summary",
        mode="replay",
        cache_root=tmp_path / "cache",
    )
    restored = await module.summarize(
        comparison, replace(deps, runtime=replay), "Fixture summary", policy
    )
    assert result == restored and len(summary_model[1]) == 1
    assert len(runtime.model.ledger.entries) == len(replay.model.ledger.entries) == 1
    assert replay.model.ledger.cost_usd == 0


@pytest.fixture
def summary_model() -> tuple[FunctionModel, list[None]]:
    calls: list[None] = []

    def response(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(None)
        assert info.output_tools is not None
        return ModelResponse(
            [
                ToolCallPart(
                    info.output_tools[0].name,
                    {"summary": "The targets select the same buyer with unchanged conviction."},
                )
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
        )

    return FunctionModel(response), calls
