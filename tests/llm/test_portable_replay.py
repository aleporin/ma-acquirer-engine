"""Specify portable archive integrity and selection compatibility.

Owns: Keyless archive loading, tamper rejection, and stale-target protection.
Does not own: Provider calls or replacing historical response content.
"""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from acquirer_engine import portable_replay as module
from acquirer_engine.deps import Deps
from acquirer_engine.errors import LLMInvalidOutput
from acquirer_engine.feedback.ranking import FeedbackPolicy
from acquirer_engine.feedback.state import BuyerFlag, FeedbackState
from acquirer_engine.pipeline import execute_prepared
from acquirer_engine.selection import Selection
from tests.llm.test_analyst import tool_model
from tests.llm.test_run_archive import inputs

DEFAULT_POLICY = FeedbackPolicy(similarity_penalty=0.15)
EMPTY_FEEDBACK = FeedbackState()


async def bundle_fixture(
    root: Path,
    deps: Deps,
    *,
    feedback_policy: FeedbackPolicy | None = DEFAULT_POLICY,
    feedback: FeedbackState = EMPTY_FEEDBACK,
) -> tuple[Path, Selection]:
    directory = root / "cache/replay" / ("b" * 32)
    snapshot = inputs(deps, directory.name).model_copy(
        update={"feedback": feedback, "feedback_policy": feedback_policy}
    )
    await execute_prepared(snapshot, directory, deps, model=tool_model(), mode="test")
    manifest = {
        "run_id": directory.name,
        "sha256": {
            name: sha256((directory / name).read_bytes()).hexdigest()
            for name in ("snapshot.json", "run.json", "trace.jsonl")
        },
    }
    (directory.parent / "manifest.json").write_text(json.dumps(manifest))
    (root / "prompts").mkdir()
    (root / "prompts" / deps.settings.analyst.prompt_file).write_text(snapshot.prompt)
    selected = Selection(
        snapshot.history, snapshot.packs, snapshot.feedback, FeedbackPolicy(similarity_penalty=0.15)
    )
    return directory, selected


@pytest.mark.asyncio
async def test_portable_archive_matches_selected_inputs_and_checks_all_file_hashes(
    tmp_path: Path, deps: Deps
) -> None:
    directory, selected = await bundle_fixture(tmp_path, deps)
    chosen = module.select_replay(tmp_path, deps, selected)
    assert chosen is not None and chosen[0] == directory
    assert chosen[1].run_id == directory.name
    with (directory / "trace.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(LLMInvalidOutput, match="checksum"):
        module.select_replay(tmp_path, deps, selected)


@pytest.mark.asyncio
async def test_portable_replay_refuses_changed_recorded_feedback_policy(
    tmp_path: Path, deps: Deps
) -> None:
    _, selected = await bundle_fixture(tmp_path, deps)
    changed_policy = FeedbackPolicy(similarity_penalty=0.2)
    changed = Selection(selected.history, selected.packs, selected.feedback, changed_policy)
    with pytest.raises(LLMInvalidOutput, match="feedback policy"):
        module.select_replay(tmp_path, deps, changed)


@pytest.mark.asyncio
async def test_portable_replay_allows_legacy_empty_feedback_without_policy(
    tmp_path: Path, deps: Deps
) -> None:
    directory, selected = await bundle_fixture(tmp_path, deps, feedback_policy=None)
    chosen = module.select_replay(tmp_path, deps, selected)
    assert chosen is not None and chosen[0] == directory


@pytest.mark.asyncio
async def test_portable_replay_refuses_legacy_feedback_without_recorded_policy(
    tmp_path: Path, deps: Deps
) -> None:
    feedback = FeedbackState(flags=(BuyerFlag(acquirer="Legacy Buyer", reason="Excluded"),))
    _, selected = await bundle_fixture(
        tmp_path, deps, feedback_policy=None, feedback=feedback
    )
    with pytest.raises(LLMInvalidOutput, match="feedback policy"):
        module.select_replay(tmp_path, deps, selected)


@pytest.mark.asyncio
async def test_portable_replay_refuses_target_changes_without_falling_back_to_live(
    tmp_path: Path, deps: Deps
) -> None:
    _, selected = await bundle_fixture(tmp_path, deps)
    pack = selected.packs[0]
    changed = pack.model_copy(
        update={"target": pack.target.model_copy(update={"deal_size_mm": 500})}
    )
    selected = Selection(selected.history, (changed,), selected.feedback, selected.feedback_policy)
    with pytest.raises(LLMInvalidOutput, match="target|selection"):
        module.select_replay(tmp_path, deps, selected)


@pytest.mark.asyncio
async def test_portable_replay_refuses_changed_prompt(tmp_path: Path, deps: Deps) -> None:
    _, selected = await bundle_fixture(tmp_path, deps)
    (tmp_path / "prompts" / deps.settings.analyst.prompt_file).write_text("Changed instructions")
    with pytest.raises(LLMInvalidOutput, match="prompt|policy"):
        module.select_replay(tmp_path, deps, selected)


def test_absent_portable_archive_keeps_existing_response_cache_behavior(
    tmp_path: Path, deps: Deps
) -> None:
    snapshot = inputs(deps, "a" * 32)
    selected = Selection(
        snapshot.history, snapshot.packs, snapshot.feedback, FeedbackPolicy(similarity_penalty=0.15)
    )
    assert module.select_replay(tmp_path, deps, selected) is None
