"""Grade the verifier against independently labeled fixture pages.

Owns: Fixture-only claim verification and planted-error detection metrics.
Does not own: Live first-pass quality, repair rates, or semantic truth.
"""

from acquirer_engine.settings import LayerSpec
from evals.grounded import GroundedReport
from evals.scorecard import LayerResult, Metric


def grade(layer: LayerSpec, report: GroundedReport | None = None) -> LayerResult:
    """Require every positive and negative fixture to meet its expectation.

    Args:
        layer: Configured layer identity.
        report: Measured fixture suite, absent for historical stub evaluations.
    Returns:
        A result with explicitly fixture-scoped measurements.
    """
    if report is None:
        return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    failures = [case.name for case in report.cases if not case.expectation_met]
    values = {
        "positive_fixtures_accepted": report.positive_accepted,
        "negative_fixtures_rejected": report.negative_rejected,
        "fixture_expectation_rate": 1 - len(failures) / len(report.cases),
        "positive_fixture_claim_verification_rate": (
            report.verified_positive_claims / report.positive_claims
            if report.positive_claims
            else 0
        ),
        "stray_numbers_detected": report.stray_numbers_detected,
    }
    return LayerResult(
        id=layer.id,
        name=layer.name,
        selected=True,
        status="failed" if failures else "passed",
        metrics={name: Metric(value=value, direction="higher") for name, value in values.items()},
    )
