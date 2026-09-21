"""Measure isolated tests from their JUnit and coverage artifacts.

Owns: Test execution, result parsing, and unit-layer measurements.
Does not own: Re-running the entire evaluation command recursively.
"""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import LayerSpec
from evals.scorecard import LayerResult, Metric


@dataclass(frozen=True)
class UnitReport:
    """Observed results from one isolated numeric/evidence test invocation."""

    total: int
    passed: int
    failed: int
    skipped: int
    coverage: float
    exit_code: int


def read_test_report(junit: Path, coverage: Path, *, exit_code: int) -> UnitReport:
    """Parse executable test output rather than inferring success from source.

    Args:
        junit: Pytest JUnit XML.
        coverage: Coverage JSON emitted for the same invocation.
        exit_code: Actual pytest process status.
    Returns:
        Counts and measured coverage fraction.
    Raises:
        EvaluationError: Results are missing or inconsistent.
    """
    try:
        suites = ET.parse(junit).getroot().iter("testsuite")
        counts = [dict(suite.attrib) for suite in suites]
        total = sum(int(suite["tests"]) for suite in counts)
        failed = sum(
            int(suite.get("failures", 0)) + int(suite.get("errors", 0)) for suite in counts
        )
        skipped = sum(int(suite.get("skipped", 0)) for suite in counts)
        fraction = float(json.loads(coverage.read_text())["totals"]["percent_covered"]) / 100
        if total < 1 or failed + skipped > total or not 0 <= fraction <= 1:
            raise ValueError("Invalid test measurements")
    except (OSError, ET.ParseError, KeyError, TypeError, ValueError) as error:
        raise EvaluationError("Invalid unit-test evidence") from error
    return UnitReport(total, total - failed - skipped, failed, skipped, fraction, exit_code)


def run_tests(project: Path, *, timeout: int) -> UnitReport:
    """Run data, ranking, and evidence tests with network-denying fixtures.

    Args:
        project: Repository containing tests and installed development dependencies.
        timeout: Maximum test-process duration in seconds.
    Returns:
        Measurements from the actual subprocess.
    Raises:
        EvaluationError: Tests cannot run or emit valid artifacts.
    """
    with TemporaryDirectory(prefix="ranking-tests-") as temporary:
        root = Path(temporary)
        junit, coverage = root / "junit.xml", root / "coverage.json"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "tests/data",
            "tests/features",
            "tests/ranking",
            "tests/evidence",
            "tests/validation",
            "tests/test_ranking_config.py",
            "-q",
            "--tb=short",
            f"--junitxml={junit}",
            "--cov=acquirer_engine.data",
            "--cov=acquirer_engine.features",
            "--cov=acquirer_engine.ranking",
            "--cov=acquirer_engine.evidence",
            "--cov=acquirer_engine.validation",
            "--cov-branch",
            f"--cov-report=json:{coverage}",
        ]
        try:
            result = subprocess.run(
                command, cwd=project, capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvaluationError("Could not execute isolated ranking tests") from error
        return read_test_report(junit, coverage, exit_code=result.returncode)


def grade(layer: LayerSpec, report: UnitReport | None = None) -> LayerResult:
    """Translate measured test evidence into the unit layer.

    Args:
        layer: Registered layer identity.
        report: Actual test results, absent for the historical stub harness.
    Returns:
        Test status and measurements, or an explicit unimplemented placeholder.
    """
    result = LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    if report is None:
        return result
    return result.model_copy(
        update={
            "status": "passed" if report.exit_code == 0 and report.failed == 0 else "failed",
            "metrics": {
                "tests": Metric(value=report.total, direction="higher"),
                "pass_rate": Metric(value=report.passed / report.total, direction="higher"),
                "coverage": Metric(value=report.coverage, direction="higher"),
            },
        }
    )
