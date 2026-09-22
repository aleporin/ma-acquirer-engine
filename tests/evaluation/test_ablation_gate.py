"""Preserve evidence rejection independently of later resource termination.

Owns: The Phase 4 gate's positive and negative control requirements.
Does not own: Provider execution or unmeasured model quality.
"""

from pathlib import Path

import pytest

from acquirer_engine.llm.results import (
    AnalystRun,
    PageAttempt,
    PageResult,
    ReviewResult,
    ReviewVerdict,
)
from acquirer_engine.settings import LayerSpec, Settings
from evals.phase1 import PreparedEvaluation
from evals.phase4 import prepare_phase4
from evals.scorecard import LayerResult
from tests.fixtures.observations import observation


def failed_attempts(terminal: str, rejected: bool, recovered: bool) -> list[PageAttempt]:
    initial = PageAttempt(
        stage="analyst",
        status="failed",
        claims_total=4,
        claims_verified=4,
        errors=["valuation_context: MA-2024-0001 requires a retrieved Closed comp"],
    )
    final = PageAttempt(
        stage="escalation",
        status="verified" if recovered else "failed",
        errors=[] if recovered else [terminal],
        claims_total=0,
        claims_verified=0,
    )
    return [initial, final] if rejected else [final]


def ablated_pages(
    pages: list[PageResult], attempts: list[PageAttempt], recovered: bool
) -> list[PageResult]:
    return [
        p.model_copy(
            update={
                "status": "verified" if recovered else "failed",
                "tools": [],
                "rationale": p.rationale if recovered else None,
                "attempts": attempts,
                "errors": attempts[-1].errors,
            }
        )
        for p in pages
    ]


def measured_cohort(
    settings: Settings, root: Path, terminal: str, *, rejected: bool = True, recovered: bool = False
) -> list[Path]:
    paths = []
    for index, (tools, reviewer) in enumerate([(True, True), (False, True), (True, False)]):
        run = observation(settings, index)
        attempts = failed_attempts(terminal, rejected, recovered)
        pages = run.pages if tools else ablated_pages(run.pages, attempts, recovered)
        review = (
            ReviewResult(
                verdicts=[
                    ReviewVerdict(acquirer=p.acquirer, decision="approve", critique="")
                    for p in pages
                ]
            )
            if reviewer
            else None
        )
        run = run.model_copy(
            update={
                "mode": "live",
                "tools_enabled": tools,
                "reviewer_enabled": reviewer,
                "pages": pages,
                "review": review,
                "calls": [
                    c.model_copy(update={"mode": "live", "cost_usd": 0.02}) for c in run.calls
                ],
            }
        )
        path = root / f"{index}.json"
        path.write_text(run.model_dump_json())
        paths.append(path)
    return paths


def operations(settings: Settings, paths: list[Path]) -> LayerResult:
    prepared = PreparedEvaluation(
        {
            i: lambda layer: LayerResult(
                id=layer.id, name=layer.name, selected=True, status="passed"
            )
            for i in (2, 5)
        },
        {},
    )
    return prepare_phase4(prepared, paths, settings).graders[6](LayerSpec(id=6, name="ops"))


@pytest.mark.parametrize("reviewer", [False, True])
@pytest.mark.parametrize(
    "terminal", ["Run USD budget cannot admit another request", "Run deadline exceeded"]
)
def test_later_limits_do_not_erase_tools_disabled_evidence_rejections(
    settings: Settings, tmp_path: Path, terminal: str, reviewer: bool
) -> None:
    settings = settings.model_copy(
        update={
            "scoring": settings.scoring.model_copy(update={"top_k": 2}),
            "analyst": settings.analyst.model_copy(update={"reviewer_enabled": reviewer}),
        }
    )
    result = operations(settings, measured_cohort(settings, tmp_path, terminal))
    assert result.metrics["live_tools_disabled_validation_failure_rate"].value == 0
    assert result.metrics["live_tools_disabled_evidence_rejection_rate"].value == 1
    assert result.metrics["live_gate_met"].value == 1
    assert result.metrics["live_tools_disabled_budget_termination_rate"].direction == "lower"
    assert result.metrics["live_tools_disabled_deadline_termination_rate"].direction == "lower"
    assert result.status == "passed"


@pytest.mark.parametrize(("rejected", "recovered"), [(False, False), (True, True)])
def test_tools_control_requires_real_rejection_and_no_successful_output(
    settings: Settings, tmp_path: Path, rejected: bool, recovered: bool
) -> None:
    settings = settings.model_copy(
        update={"scoring": settings.scoring.model_copy(update={"top_k": 2})}
    )
    paths = measured_cohort(
        settings, tmp_path, "Run deadline exceeded", rejected=rejected, recovered=recovered
    )
    result = operations(settings, paths)
    assert result.metrics["live_gate_met"].value == 0
    assert result.status == "failed"


def test_phase_gate_requires_both_reviewer_variants(settings: Settings, tmp_path: Path) -> None:
    settings = settings.model_copy(
        update={"scoring": settings.scoring.model_copy(update={"top_k": 2})}
    )
    paths = measured_cohort(settings, tmp_path, "Run deadline exceeded")
    assert operations(settings, paths[1:]).status == "failed"


@pytest.mark.parametrize("count", [0, 1])
def test_review_success_requires_a_verdict_for_every_buyer(
    settings: Settings, tmp_path: Path, count: int
) -> None:
    settings = settings.model_copy(
        update={"scoring": settings.scoring.model_copy(update={"top_k": 2})}
    )
    paths = measured_cohort(settings, tmp_path, "Run deadline exceeded")
    reviewed = AnalystRun.model_validate_json(
        paths[0].read_text(), context=settings.evidence.validation
    )
    assert reviewed.review is not None
    review = reviewed.review.model_copy(update={"verdicts": reviewed.review.verdicts[:count]})
    paths[0].write_text(reviewed.model_copy(update={"review": review}).model_dump_json())
    assert operations(settings, paths).status == "failed"


def test_missing_normal_cohort_produces_a_failed_gate(settings: Settings, tmp_path: Path) -> None:
    paths = measured_cohort(settings, tmp_path, "Run deadline exceeded")
    assert operations(settings, paths[:2]).status == "failed"
