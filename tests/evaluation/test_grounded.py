"""Measure the verifier against independent good and planted-bad pages.

Owns: Fixture acceptance, error specificity, and groundedness grading.
Does not own: Live-generation or post-repair quality claims.
"""

import json
from pathlib import Path
from shutil import copytree

import pytest

from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import Settings
from evals.graders.grounded import grade
from evals.grounded import run_fixture_suite


def test_grounded_suite_accepts_three_good_and_rejects_six_bad(settings: Settings) -> None:
    report = run_fixture_suite(Path("evals/fixtures/grounded"), settings.evidence.validation)
    assert report.positive_cases == 3 and report.positive_accepted == 3
    assert report.negative_cases == 6 and report.negative_rejected == 6
    assert all(case.expectation_met for case in report.cases)
    result = grade(settings.evaluation.layers[2], report)
    assert result.status == "passed"
    assert result.metrics["positive_fixture_claim_verification_rate"].value == 1
    assert result.metrics["stray_numbers_detected"].value == 1


def test_a_bad_fixture_that_slips_through_fails_the_grader(
    settings: Settings, tmp_path: Path
) -> None:
    root = tmp_path / "fixtures"
    copytree("evals/fixtures/grounded", root)
    page = root / "bad_wrong_number.json"
    payload = json.loads((root / "good_rounding.json").read_text())
    page.write_text(json.dumps(payload))
    report = run_fixture_suite(root, settings.evidence.validation)
    result = grade(settings.evaluation.layers[2], report)
    assert result.status == "failed"
    assert report.negative_rejected == 5
    assert [case.name for case in report.cases if not case.expectation_met] == ["bad_wrong_number"]


def test_missing_fixture_is_not_a_passing_empty_suite(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(EvaluationError, match="fixture"):
        run_fixture_suite(tmp_path, settings.evidence.validation)
