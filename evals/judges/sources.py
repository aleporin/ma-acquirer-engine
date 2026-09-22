"""Select judge cases from complete, clean generation archives.

Owns: Source identity checks and before/after page pairing.
Does not own: New generation, provider calls, or mutable ranking configuration.
"""

import hashlib
from pathlib import Path

from pydantic import ValidationError

from acquirer_engine.data import Transaction
from acquirer_engine.errors import AcquirerEngineError, EvaluationError
from acquirer_engine.evidence.pack import CorePack, Statistic
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.replay import RunSnapshot, load_snapshot
from evals.judges.facts import candidate_summary, evidence_text, page_text, source_facts
from evals.judges.schema import Candidate, Case


def _check_source(report: AnalystRun, snapshot: RunSnapshot, candidate_count: int) -> None:
    if report.mode != "live" or report.source_dirty or snapshot.source_dirty:
        raise EvaluationError("Judge cases require clean original live generations")
    if (
        report.run_id != snapshot.run_id
        or report.git_sha != snapshot.git_sha
        or report.prompt_version != snapshot.settings.evaluation.prompt_version
        or report.reviewer_enabled != snapshot.settings.analyst.reviewer_enabled
    ):
        raise EvaluationError("Run and snapshot provenance differ")
    expected = {pack.ranking.acquirer for pack in snapshot.packs}
    groups = [report.pages]
    if report.reviewer_enabled:
        groups.append(report.before_review)
    if len(snapshot.packs) != candidate_count or len(expected) != candidate_count:
        raise EvaluationError("Candidate inventory is incomplete or duplicated")
    for pages in groups:
        if len(pages) != candidate_count or {page.acquirer for page in pages} != expected:
            raise EvaluationError("Page inventory is incomplete or duplicated")
        if any(page.status != "verified" or page.rationale is None for page in pages):
            raise EvaluationError("Judge calibration requires complete verified pages")
    if report.review and report.review.errors:
        raise EvaluationError("Reviewer failed; this is not a complete calibration source")


def _case(
    page: PageResult,
    stage: str,
    report: AnalystRun,
    pack: CorePack,
    candidates: tuple[Candidate, ...],
    facts: dict[str, Transaction | Statistic],
) -> Case:
    assert page.rationale is not None
    text = page_text(page.rationale)
    evidence = evidence_text(page.rationale, pack, facts)
    identity = "\n".join((report.run_id, page.acquirer, stage, text, evidence))
    return Case.model_validate(
        {
            "case_id": "case-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
            "source_run_id": report.run_id,
            "source_git_sha": report.git_sha,
            "generation_prompt": report.prompt_version,
            "buyer": page.acquirer,
            "stage": stage,
            "reviewer_enabled": report.reviewer_enabled,
            "page": text,
            "evidence": evidence,
            "target": pack.target.model_dump_json(),
            "candidates": candidates,
        }
    )


def load_cases(directory: Path, candidate_count: int) -> list[Case]:
    """Read one frozen source, including paired pre-review pages when applicable.

    Args:
        directory: Original run directory containing snapshot.json and run.json.
        candidate_count: Expected ranked portfolio size from judge configuration.
    Returns:
        Cases retaining generation identity and reviewer stage independently.
    Raises:
        EvaluationError: The source is missing, malformed, incomplete, or inconsistent.
    """
    try:
        snapshot = load_snapshot(directory)
        report = AnalystRun.model_validate_json(
            (directory / "run.json").read_bytes(), context=snapshot.settings.evidence.validation
        )
        _check_source(report, snapshot, candidate_count)
        packs = {pack.ranking.acquirer: pack for pack in snapshot.packs}
        candidates = tuple(candidate_summary(pack, snapshot.history) for pack in snapshot.packs)
        facts = source_facts(snapshot)
        stages = [("after_review", report.pages)]
        if report.reviewer_enabled:
            stages.append(("before_review", report.before_review))
        return [
            _case(page, stage, report, packs[page.acquirer], candidates, facts)
            for stage, pages in stages
            for page in pages
        ]
    except (OSError, ValidationError, AcquirerEngineError) as error:
        raise EvaluationError(f"Invalid judge source {directory.name}: {error}") from error
