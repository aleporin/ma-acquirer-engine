"""Exercise measured layer assembly and the conviction exit gate.

Owns: Scorecard measurements, snapshots, and grader integration.
Does not own: Running live providers or tuning quality targets.
"""

import json
from pathlib import Path

from evals.phase1 import prepare_phase1

from acquirer_engine.deps import Deps
from acquirer_engine.settings import LayerSpec
from evals.graders.unit import read_test_report
from evals.scorecard import LayerResult, Metric
from tests.fixtures.ranking import transaction


def test_junit_and_coverage_are_measured_from_artifacts(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="4" failures="1" errors="0" skipped="1"/></testsuites>'
    )
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"totals": {"percent_covered": 75.0}}))
    report = read_test_report(junit, coverage, exit_code=1)
    assert report.total == 4
    assert report.passed == 2
    assert report.failed == 1
    assert report.skipped == 1
    assert report.coverage == 0.75


def test_phase_one_produces_measurements_and_reports_unmet_conviction_gate(deps: Deps) -> None:
    rows = [
        transaction(1, sector="Healthcare Services"),
        transaction(2, sector="Healthcare Services", deal_year=2022),
    ]
    unit = LayerResult(
        id=0,
        name="unit_and_property_tests",
        selected=True,
        status="passed",
        metrics={"pass_rate": Metric(value=1, direction="higher")},
    )
    prepared = prepare_phase1(rows, deps, unit)
    backtest = prepared.graders[1](LayerSpec(id=1, name="ranking_backtest"))
    stability = prepared.graders[5](LayerSpec(id=5, name="stability"))
    assert backtest.status == "passed"
    assert "ranker_recall_at_k" in backtest.metrics
    assert stability.metrics["top_k_identity"].value == 1
    assert stability.metrics["conviction_levels"].value == 1
    assert stability.status == "failed"
    assert {"backtest.json", "data_quality.json", "top10.json"} <= set(prepared.artifacts)
    snapshot = json.loads(prepared.artifacts["top10.json"])
    assert snapshot["stability_runs"] == 5
    assert len(snapshot["acquirers"]) == 1
