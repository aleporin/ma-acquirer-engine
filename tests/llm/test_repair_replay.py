"""Preserve repaired output across execution-structure changes.

Owns: Replayed validation attempts, public page bytes, and immutable source files.
Does not own: Live model quality or exact execution timings.
"""

from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.llm.archive import load_snapshot
from acquirer_engine.pipeline import execute_prepared, execute_replay
from acquirer_engine.report.render import render_report
from tests.llm.test_repair import correcting_model, enabled
from tests.llm.test_run_archive import inputs


def page_body(directory: Path) -> str:
    """Compare public content separately from the deliberately new run footer."""
    return (directory / "buyers/01.md").read_text().rsplit("\n---\n", 1)[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("correct", [True, False], ids=["repaired", "exhausted"])
async def test_replay_preserves_repair_outcomes_and_rendered_page(
    deps: Deps, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, correct: bool
) -> None:
    deps = enabled(deps)
    snapshot = inputs(deps, "b" * 32)
    original, replayed = tmp_path / snapshot.run_id, tmp_path / ("c" * 32)
    baseline = await execute_prepared(
        snapshot, original, deps, model=correcting_model("schema", [], correct=correct), mode="test"
    )
    render_report(snapshot, baseline, original)
    frozen = {
        str(p.relative_to(original)): p.read_bytes() for p in original.rglob("*") if p.is_file()
    }

    def no_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("Replay must not construct a provider client")

    monkeypatch.setattr("acquirer_engine.bootstrap.create_client", no_client)
    replay = await execute_replay(original, replayed, snapshot, deps, "d" * 40)
    render_report(load_snapshot(replayed), replay, replayed)
    expected = baseline.pages[0]
    assert [attempt.status for attempt in expected.attempts] == [
        "failed",
        "verified" if correct else "failed",
    ]
    assert replay.pages[0].model_dump(exclude={"latency_seconds"}) == expected.model_dump(
        exclude={"latency_seconds"}
    )
    assert page_body(replayed) == page_body(original)
    assert len(replay.calls) == len(baseline.calls) == 3
    assert [call.stage for call in replay.calls] == ["analyst", "analyst", "repair"]
    assert all(call.mode == "replay" and call.cost_usd == 0 for call in replay.calls)
    assert {
        str(p.relative_to(original)): p.read_bytes() for p in original.rglob("*") if p.is_file()
    } == frozen
