"""Execute labeled rationale fixtures through the real verifier.

Owns: Fixture loading, observed failures, and reproducible suite measurements.
Does not own: Live generation, repair, or reporting fixture quality as live quality.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from acquirer_engine.errors import EvaluationError, ValidationFailure
from acquirer_engine.evidence.config import ValidationConfig
from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.validation.claims import validate_rationale
from acquirer_engine.validation.schema import AcquirerRationale


class FixtureSpec(BaseModel):
    """A named page and its independently labeled expected failure."""

    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(pattern=r"^[a-z_]+$")]
    expected_error: str | None


class FixtureResult(BaseModel):
    """Observed verifier output for one labeled page."""

    name: str
    expected_error: str | None
    accepted: bool
    errors: list[str]
    expectation_met: bool
    claim_count: int


class GroundedReport(BaseModel):
    """Fixture-only evidence; post-repair and live rates remain unmeasured."""

    scope: Literal["hand_written_fixtures"] = "hand_written_fixtures"
    fixture_sha256: str
    cases: list[FixtureResult]
    positive_cases: int
    positive_accepted: int
    negative_cases: int
    negative_rejected: int
    positive_claims: int
    verified_positive_claims: int
    stray_numbers_detected: int


def _run_case(
    spec: FixtureSpec, payload: object, context: EvidenceContext, config: ValidationConfig
) -> FixtureResult:
    errors: list[str] = []
    try:
        parsed = AcquirerRationale.model_validate(payload, context=config)
        count = len(parsed.claims)
    except ValidationError:
        count = 0
    try:
        validate_rationale(payload, context, config)
    except ValidationFailure as error:
        errors = list(error.errors)
    accepted = not errors
    expected = spec.expected_error
    return FixtureResult(
        name=spec.name,
        expected_error=expected,
        accepted=accepted,
        errors=errors,
        expectation_met=accepted
        if expected is None
        else any(expected in error for error in errors),
        claim_count=count,
    )


def run_fixture_suite(directory: Path, config: ValidationConfig) -> GroundedReport:
    """Run every manifest page and preserve actual, specific validation errors.

    Args:
        directory: Local fixture manifest, context, and independently written pages.
        config: The same policy used for product validation.
    Returns:
        Fixture counts, identity, and observed per-page outcomes.
    Raises:
        EvaluationError: Fixture inputs are absent, malformed, or incomplete.
    """
    digest = hashlib.sha256()
    try:
        manifest = (directory / "manifest.json").read_bytes()
        specs = TypeAdapter(list[FixtureSpec]).validate_json(manifest)
        if not specs or len({spec.name for spec in specs}) != len(specs):
            raise ValueError("Fixture manifest must contain unique cases")
        context_bytes = (directory / "context.json").read_bytes()
        context = EvidenceContext.model_validate_json(context_bytes)
        digest.update(manifest + context_bytes)
        cases = []
        for spec in specs:
            content = (directory / f"{spec.name}.json").read_bytes()
            digest.update(content)
            cases.append(_run_case(spec, json.loads(content), context, config))
    except (OSError, ValueError, ValidationError) as error:
        raise EvaluationError("Invalid groundedness fixture inputs") from error
    return _report(cases, digest.hexdigest())


def _report(cases: list[FixtureResult], fingerprint: str) -> GroundedReport:
    positive = [case for case in cases if case.expected_error is None]
    negative = [case for case in cases if case.expected_error is not None]
    if not positive or not negative:
        raise EvaluationError("Groundedness fixtures require positive and negative cases")
    return GroundedReport(
        fixture_sha256=fingerprint,
        cases=cases,
        positive_cases=len(positive),
        positive_accepted=sum(case.accepted for case in positive),
        negative_cases=len(negative),
        negative_rejected=sum(not case.accepted for case in negative),
        positive_claims=sum(case.claim_count for case in positive),
        verified_positive_claims=sum(case.claim_count for case in positive if case.accepted),
        stray_numbers_detected=sum(
            "stray number" in error for case in cases for error in case.errors
        ),
    )
