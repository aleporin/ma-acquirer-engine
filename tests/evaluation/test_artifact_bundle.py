"""Verify scorecards publish related artifacts as one bundle.

Owns: Artifact bytes and filename safety.
Does not own: Computing ranking metrics.
"""

from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from evals.harness import evaluate
from evals.scorecard import RunInfo, write_scorecard


def test_supplementary_artifacts_are_written_with_scorecard(
    deps: Deps, run: RunInfo, tmp_path: Path
) -> None:
    card = evaluate(deps, run, [0])
    path = write_scorecard(card, tmp_path, artifacts={"top10.json": "[]\n"})
    assert path.with_name("top10.json").read_text() == "[]\n"


@pytest.mark.parametrize(
    "name", ["../escape.json", "/tmp/escape.json", "scorecard.json", "summary.md"]
)
def test_unsafe_or_reserved_artifacts_are_rejected(
    deps: Deps, run: RunInfo, tmp_path: Path, name: str
) -> None:
    card = evaluate(deps, run, [0])
    with pytest.raises(EvaluationError, match="artifact"):
        write_scorecard(card, tmp_path, artifacts={name: "{}"})
    assert list(tmp_path.iterdir()) == []
