"""Exercise run-specific replay independently of the mutable request cache.

Owns: Frozen inputs, archived responses, and public historical replay behavior.
Does not own: Provider quality or reproducing old verifier implementations.
"""

import asyncio
import json
from inspect import isawaitable
from pathlib import Path
from shutil import rmtree

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from typer.testing import CliRunner

from acquirer_engine.cli import build_app
from acquirer_engine.deps import Deps
from acquirer_engine.llm.archive import RunSnapshot, load_snapshot
from acquirer_engine.pipeline import execute_prepared
from tests.fixtures.rationale import evidence_context
from tests.llm.test_analyst import tool_model


def inputs(deps: Deps, run_id: str) -> RunSnapshot:
    context = evidence_context(deps.settings)
    return RunSnapshot(
        run_id=run_id,
        git_sha="a" * 40,
        settings=deps.settings,
        prompt="Original fixture instructions.",
        history=context.core.deals + context.comparable_deals,
        packs=(context.core,),
    )


@pytest.mark.asyncio
async def test_snapshot_is_written_before_the_first_model_request(
    deps: Deps, tmp_path: Path
) -> None:
    directory = tmp_path / "runs" / ("b" * 32)
    snapshot = inputs(deps, directory.name)
    delegate = tool_model()

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert load_snapshot(directory) == snapshot
        assert delegate.function is not None
        result = delegate.function(messages, info)
        return await result if isawaitable(result) else result

    report = await execute_prepared(
        snapshot, directory, deps, model=FunctionModel(respond), mode="test"
    )
    assert report.pages[0].status == "verified"
    assert json.loads((directory / "run.json").read_text())["run_id"] == snapshot.run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("source_dirty", [False, True])
async def test_cli_replays_original_inputs_with_no_current_files_or_cache(
    deps: Deps, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_dirty: bool
) -> None:
    original = tmp_path / "runs" / ("b" * 32)
    snapshot = inputs(deps, original.name)
    baseline = await execute_prepared(snapshot, original, deps, model=tool_model(), mode="test")
    original_bytes = {p.name: p.read_bytes() for p in original.iterdir() if p.is_file()}
    rmtree(original / "cache")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/analyst.yaml").write_text("invalid: current configuration")
    monkeypatch.setattr("acquirer_engine.run_history.git_state", lambda _: ("c" * 40, source_dirty))

    def no_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("Historical replay must not construct a provider client")

    monkeypatch.setattr("acquirer_engine.bootstrap.create_client", no_client)
    result = await asyncio.to_thread(
        CliRunner().invoke, build_app(), ["replay", original.name, "--project", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    paths = [p for p in (tmp_path / "runs").glob("*/run.json") if p.parent != original]
    report = json.loads(paths[0].read_text())
    assert report["mode"] == "replay" and report["replay_of"] == original.name
    assert report.get("source_dirty") is source_dirty
    assert load_snapshot(paths[0].parent).model_dump().get("source_dirty") is source_dirty
    assert report["git_sha"] == "c" * 40 and report["source_git_sha"] == "a" * 40
    assert report["prompt_version"] == snapshot.settings.evaluation.prompt_version
    assert baseline.pages[0].rationale is not None
    assert report["pages"][0]["rationale"] == baseline.pages[0].rationale.model_dump(mode="json")
    assert len(report["calls"]) == 2 and sum(c["cost_usd"] for c in report["calls"]) == 0
    assert {p.name: p.read_bytes() for p in original.iterdir() if p.is_file()} == original_bytes
    listing = CliRunner().invoke(build_app(), ["runs", "--project", str(tmp_path)])
    assert listing.exit_code == 0, listing.output
    assert original.name in listing.output and report["run_id"] in listing.output
    assert "1/1" in listing.output


@pytest.mark.parametrize("run_id", ["../private", "unknown", "f" * 32])
def test_replay_rejects_invalid_or_missing_archive_without_current_config(
    tmp_path: Path, run_id: str
) -> None:
    result = CliRunner().invoke(build_app(), ["replay", run_id, "--project", str(tmp_path)])
    assert result.exit_code == 1
    assert "archive" in result.output.lower()


def test_saved_snapshot_preserves_legacy_execution_policy_fields(
    deps: Deps, tmp_path: Path
) -> None:
    from acquirer_engine.llm.archive import save_snapshot
    from acquirer_engine.llm.config import AnalystConfig

    snapshot = inputs(deps, "a" * 32)
    old_fields = {
        k: v
        for k, v in deps.settings.analyst.model_dump().items()
        if k
        not in {
            "max_repairs",
            "tools_enabled",
            "escalation_enabled",
            "reviewer_enabled",
            "sparse_prompt_file",
            "sparse_relevant_deals",
            "max_run_usd",
            "request_overhead_tokens",
            "run_timeout_seconds",
            "reviewer_prompt_file",
            "reviewer_max_output_tokens",
        }
    }
    old = AnalystConfig.model_validate(old_fields)
    snapshot = snapshot.model_copy(
        update={"settings": deps.settings.model_copy(update={"analyst": old})}
    )
    directory = tmp_path / snapshot.run_id
    save_snapshot(directory, snapshot)
    restored = load_snapshot(directory).settings.analyst
    assert restored.model_dump(exclude_unset=True) == old.model_dump(exclude_unset=True)


def test_snapshot_without_feedback_fields_loads_as_empty_legacy_state(
    deps: Deps, tmp_path: Path
) -> None:
    snapshot = inputs(deps, "a" * 32)
    directory = tmp_path / snapshot.run_id
    directory.mkdir()
    payload = snapshot.model_dump(mode="json")
    payload.pop("feedback")
    payload.pop("feedback_policy")
    (directory / "snapshot.json").write_text(json.dumps(payload) + "\n")
    restored = load_snapshot(directory)
    assert not restored.feedback.flags
    assert restored.feedback_policy is None
