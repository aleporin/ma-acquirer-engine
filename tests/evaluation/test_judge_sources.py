"""Specify provenance checks at the archive-to-judge boundary.

Owns: Frozen source selection, complete pages, and before/after pairing.
Does not own: Analyst execution or live judge calls.
"""

import json
from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.llm.archive import save_snapshot
from evals.judges.sources import load_cases
from tests.fixtures.observations import observation
from tests.llm.test_run_archive import inputs


def archive(tmp_path: Path, deps: Deps) -> Path:
    directory = tmp_path / ("b" * 32)
    snapshot = inputs(deps, directory.name)
    save_snapshot(directory, snapshot)
    record = observation(deps.settings).model_copy(
        update={
            "run_id": directory.name,
            "mode": "live",
            "pages": observation(deps.settings).pages[:1],
            "prompt_version": deps.settings.evaluation.prompt_version,
        }
    )
    (directory / "run.json").write_text(record.model_dump_json())
    return directory


def test_case_uses_archived_target_and_keeps_internal_reasoning_out(
    tmp_path: Path,
    deps: Deps,
) -> None:
    directory = archive(tmp_path, deps)
    (case,) = load_cases(directory, candidate_count=1)
    assert case.source_run_id == directory.name
    assert case.source_git_sha == "a" * 40
    assert "Use the own-history" not in case.page
    assert "13.6x" in case.page and "13.64" in case.evidence
    assert "Services" in case.target and case.buyer == "Buyer A"
    assert load_cases(directory, candidate_count=1) == [case]


@pytest.mark.parametrize(
    "change", [{"source_dirty": True}, {"mode": "replay"}, {"git_sha": "c" * 40}, {"pages": []}]
)
def test_incomplete_or_unmatched_sources_fail_closed(
    tmp_path: Path,
    deps: Deps,
    change: dict[str, object],
) -> None:
    directory = archive(tmp_path, deps)
    path = directory / "run.json"
    raw = json.loads(path.read_text()) | change
    path.write_text(json.dumps(raw))
    with pytest.raises(EvaluationError):
        load_cases(directory, candidate_count=1)


def test_before_and_after_cases_retain_shared_generation_identity(
    tmp_path: Path,
    deps: Deps,
) -> None:
    directory = archive(tmp_path, deps)
    path = directory / "run.json"
    raw = json.loads(path.read_text())
    raw["reviewer_enabled"] = True
    raw["before_review"] = raw["pages"]
    path.write_text(json.dumps(raw))
    snapshot_path = directory / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["settings"]["analyst"]["reviewer_enabled"] = True
    snapshot_path.write_text(json.dumps(snapshot))
    cases = load_cases(directory, candidate_count=1)
    assert {case.stage for case in cases} == {"before_review", "after_review"}
    assert len({case.case_id for case in cases}) == 2
    assert cases[0].page == cases[1].page
    assert cases[0].source_run_id == cases[1].source_run_id
