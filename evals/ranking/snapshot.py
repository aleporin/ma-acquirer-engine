"""Check a current ranking against the latest committed snapshot.

Owns: Persisted ranking identity regression checks and explicit change markers.
Does not own: Selecting a better ranking or evaluating score deltas.
"""

import json
import subprocess
from pathlib import Path

from acquirer_engine.errors import EvaluationError
from evals.scorecard import read_scorecard


def check_snapshot(expected: list[str], actual: list[str], *, ranking_change: bool) -> None:
    """Reject an unannounced change in ordered buyer identities.

    Args:
        expected: Previously committed ranking order.
        actual: Newly computed ranking order.
        ranking_change: Whether intervening history explicitly marks ranking work.
    Raises:
        EvaluationError: Ranking identity changed without a ranking marker.
    """
    if expected != actual and not ranking_change:
        raise EvaluationError("Ranking snapshot changed without a ranking: commit marker")


def verify_snapshot(project: Path, snapshot: str) -> None:
    """Compare against tracked Phase 1 artifacts, ignoring exploratory outputs.

    Args:
        project: Repository root.
        snapshot: New serialized top-ten artifact.
    Raises:
        EvaluationError: Evidence is invalid or an unannounced regression occurred.
    """
    paths = list((project / "evals/results").glob("p1-*/scorecard.json"))
    if not paths:
        return
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "evals/results"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        cards = [
            (read_scorecard(path), path)
            for path in paths
            if str(path.relative_to(project)) in tracked
        ]
        if not cards:
            return
        card, path = max(cards, key=lambda pair: pair[0].run.created_at)
        prior = json.loads(path.with_name("top10.json").read_text())
        messages = subprocess.run(
            ["git", "log", f"{card.run.git_sha}..HEAD", "--format=%B"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        check_snapshot(
            [item["acquirer"] for item in prior["acquirers"]],
            [item["acquirer"] for item in json.loads(snapshot)["acquirers"]],
            ranking_change="ranking:" in messages,
        )
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        raise EvaluationError("Could not verify ranking snapshot") from error
