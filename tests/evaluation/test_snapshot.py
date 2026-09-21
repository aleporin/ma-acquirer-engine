"""Exercise persisted ranking identity regression checks.

Owns: Snapshot identity and explicit ranking-change authorization.
Does not own: Judging numeric score improvements.
"""

import pytest

from acquirer_engine.errors import EvaluationError
from evals.ranking.snapshot import check_snapshot


def test_identical_ranked_names_pass() -> None:
    check_snapshot(["A", "B"], ["A", "B"], ranking_change=False)


def test_changed_order_fails_without_ranking_change() -> None:
    with pytest.raises(EvaluationError, match="snapshot"):
        check_snapshot(["A", "B"], ["B", "A"], ranking_change=False)


def test_explicit_ranking_change_allows_new_snapshot() -> None:
    check_snapshot(["A", "B"], ["B", "A"], ranking_change=True)
