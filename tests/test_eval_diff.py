"""Verify metric comparison and explicit regressions.

Owns: Direction-aware deltas and missing-measurement behavior.
Does not own: Producing benchmark measurements.
"""

from datetime import UTC, datetime

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from evals.diff import compare_scorecards
from evals.harness import evaluate
from evals.scorecard import RunInfo, Scorecard


@pytest.fixture
def baseline(deps: Deps) -> Scorecard:
    run = RunInfo(git_sha="a" * 40, run_id="b" * 32, created_at=datetime(2026, 9, 21, tzinfo=UTC))
    return evaluate(deps, run, [0])


def measured(card: Scorecard, value: float, direction: str = "higher") -> Scorecard:
    data = card.model_dump(mode="json")
    data["layers"][0]["status"] = "passed"
    data["layers"][0]["metrics"] = {"measurement": {"value": value, "direction": direction}}
    return Scorecard.model_validate(data)


def test_stub_comparison_does_not_invent_zero_metrics(baseline: Scorecard) -> None:
    report = compare_scorecards(baseline, baseline)
    assert not report.regressions
    assert "No measured metrics to compare." in report.lines


@pytest.mark.parametrize("direction", ["higher", "lower"])
def test_improvement_direction_controls_regressions(baseline: Scorecard, direction: str) -> None:
    report = compare_scorecards(measured(baseline, 2, direction), measured(baseline, 1, direction))
    assert bool(report.regressions) == (direction == "higher")
    assert any("delta -1" in line for line in report.lines)


def test_lost_metric_is_a_regression(baseline: Scorecard) -> None:
    report = compare_scorecards(measured(baseline, 1), baseline)
    assert any("removed" in issue for issue in report.regressions)


def test_new_metric_is_reported_without_a_fabricated_delta(baseline: Scorecard) -> None:
    report = compare_scorecards(baseline, measured(baseline, 1))
    assert not report.regressions
    assert any("added" in line for line in report.lines)
    assert not any("delta" in line for line in report.lines)


def test_changed_direction_cannot_be_compared(baseline: Scorecard) -> None:
    with pytest.raises(EvaluationError, match="direction"):
        compare_scorecards(measured(baseline, 1), measured(baseline, 1, "lower"))


def test_pass_to_fail_is_a_regression_even_with_unchanged_metric(baseline: Scorecard) -> None:
    before = measured(baseline, 1)
    data = before.model_dump(mode="json")
    data["layers"][0]["status"] = "failed"
    report = compare_scorecards(before, Scorecard.model_validate(data))
    assert any("passed -> failed" in issue for issue in report.regressions)
