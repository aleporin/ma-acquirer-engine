"""Prepare the blind calibration cohort from immutable generation archives.

Owns: Source checks, evidence summaries, matched cohorts, and packet publication.
Does not own: Human labels, provider calls, or judge verdicts.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from acquirer_engine.data import Transaction
from acquirer_engine.errors import AcquirerEngineError, EvaluationError
from acquirer_engine.evidence.pack import CorePack, Statistic
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.llm.tools import EvidenceTools
from acquirer_engine.replay import RunSnapshot, load_snapshot
from acquirer_engine.validation.schema import AcquirerRationale
from evals.judges.cases import seal_corpus
from evals.judges.config import JudgeConfig
from evals.judges.labels import export_packet
from evals.judges.schema import Candidate, Case, Corpus


def prepare(sources: list[Path], config: JudgeConfig, corpus_path: Path, packet: Path) -> Corpus:
    """Freeze a complete cohort and export blank human labels without overwriting.

    Args:
        sources: Original generation archive directories.
        config: Explicit calibration policy.
        corpus_path, packet: New corpus JSON and blind packet destinations.
    Returns:
        Sealed source cases with the logged shuffle seed.
    Raises:
        EvaluationError: Sources are invalid or either destination already exists.
    """
    if corpus_path.exists() or packet.exists():
        raise EvaluationError("Calibration corpus or blind packet already exists")
    corpus = seal_corpus(
        [c for source in sources for c in load_cases(source, config.candidate_count)],
        seed=config.seed,
    )
    validate_cohort(corpus, config)
    export_packet(corpus, packet)
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    with corpus_path.open("x") as stream:
        stream.write(corpus.model_dump_json(indent=2) + "\n")
    return corpus


def validate_cohort(corpus: Corpus, config: JudgeConfig) -> None:
    """Require complete matched portfolios for calibration and reviewer comparison.

    Args:
        corpus, config: Frozen cases and required run/portfolio counts.
    Raises:
        EvaluationError: Source runs, buyers, stages, or target definitions differ.
    """
    final = [c for c in corpus.cases if c.stage == "after_review"]
    sources = {c.source_run_id for c in final}
    groups = [[c for c in final if c.source_run_id == source] for source in sorted(sources)]
    if len(groups) != config.calibration_runs or any(
        len(g) != config.candidate_count for g in groups
    ):
        raise EvaluationError("Incomplete calibration cohort: require configured runs and pages")
    buyers = {c.buyer for c in final}
    if len(buyers) != config.candidate_count or any({c.buyer for c in g} != buyers for g in groups):
        raise EvaluationError("Unmatched calibration buyer portfolios")
    if len({(c.source_git_sha, c.generation_prompt, c.target) for c in corpus.cases}) != 1:
        raise EvaluationError("Calibration source revision, prompt, or target differs")
    if {c.reviewer_enabled for c in final} != {True, False}:
        raise EvaluationError("Calibration requires both reviewer settings")
    for group in groups:
        if len({c.reviewer_enabled for c in group}) != 1:
            raise EvaluationError("Mixed reviewer settings within a source")
        before = [
            c
            for c in corpus.cases
            if c.source_run_id == group[0].source_run_id and c.stage == "before_review"
        ]
        expected = buyers if group[0].reviewer_enabled else set()
        if len(before) != len(expected) or {c.buyer for c in before} != expected:
            raise EvaluationError("Incomplete paired reviewer calibration pages")
    if any({x.name for x in c.candidates} != buyers for c in corpus.cases):
        raise EvaluationError("Calibration candidate inventories differ")


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


def page_text(page: AcquirerRationale) -> str:
    """Render visible sections, excluding internal reasoning and the numeric ledger.

    Args:
        page: Validated archived rationale.
    Returns:
        Plain text suitable for both blind human reading and rubric evaluation.
    """
    sections = [f"Overview: {page.acquirer_overview}", f"Thesis: {page.strategic_fit_thesis}"]
    sections.extend(
        f"Precedent {p.transaction_id}: {p.description}" for p in page.precedent_activity
    )
    sections.append(f"Valuation: {page.valuation_context.summary}")
    sections.extend(
        f"Risk ({risk.category}; {risk.basis}): {risk.description}" for risk in page.risk_flags
    )
    sections.append(f"Conviction ({page.conviction.level}): {page.conviction.justification}")
    if page.outside_dataset_notes:
        sections.append(f"Outside dataset notes: {page.outside_dataset_notes}")
    return "\n\n".join(sections)


def candidate_summary(pack: CorePack, history: tuple[Transaction, ...]) -> Candidate:
    """Summarize recorded patterns without identifying evidence-key shortcuts."""
    own = [
        row for row in history if row.acquirer == pack.ranking.acquirer and row.outcome != "Rumored"
    ]
    summary = {
        "buyer_type": pack.ranking.acquirer_type,
        "sector_counts": dict(Counter(row.sector for row in own)),
        "geographies": dict(Counter(row.geography for row in own)),
        "recorded_statistics": {
            fact.metric: fact.value for fact in pack.statistics if "." not in fact.metric
        },
        "precedent_excerpt": [
            f"{row.target_company}, {row.deal_year}, {row.sector}, "
            f"EV ${row.deal_size_mm}M, {row.outcome}"
            for row in pack.deals
        ],
        "excerpt_truncated": pack.truncated,
    }
    return Candidate(name=pack.ranking.acquirer, summary=json.dumps(summary, sort_keys=True))


def source_facts(snapshot: RunSnapshot) -> dict[str, Transaction | Statistic]:
    """Resolve historical rows and deterministic benchmarks from the frozen population.

    Args:
        snapshot: Original source population, core packs, and query policy.
    Returns:
        Source facts; these are not assertions made by a generation or judge.
    """
    index: dict[str, Transaction | Statistic] = {
        row.transaction_id: row for row in snapshot.history
    }
    tools = EvidenceTools(snapshot.history, snapshot.settings.analyst)
    for sector in sorted({row.sector for row in snapshot.history}):
        index.update({fact.evidence_id: fact for fact in tools.sector_stats(sector).statistics})
    for pack in snapshot.packs:
        index.update({fact.evidence_id: fact for fact in pack.statistics})
    return index


def _fact_text(fact: Transaction | Statistic) -> str:
    if isinstance(fact, Statistic):
        return f"{fact.evidence_id}: {fact.metric} = {fact.value}"
    return (
        f"{fact.transaction_id}: {fact.acquirer} / {fact.target_company}; {fact.sector}, "
        f"{fact.geography}, {fact.deal_year}, {fact.outcome}; EV ${fact.deal_size_mm}M; "
        f"stated EV/EBITDA {fact.ev_ebitda_multiple}x, EV/Revenue {fact.ev_revenue_multiple}x; "
        f"EBITDA margin {fact.ebitda_margin_pct}%; {fact.num_bidders} bidders; "
        f"{fact.financing_type}; {fact.deal_type}."
    )


def evidence_text(
    page: AcquirerRationale, pack: CorePack, index: dict[str, Transaction | Statistic]
) -> str:
    """Resolve cited facts and expose the original deterministic ranking explanation.

    Args:
        page, pack, index: Archived narrative and its independent factual inputs.
    Returns:
        Compact text, retaining canonical stated values rather than rounded claims.
    Raises:
        EvaluationError: A cited fact cannot be resolved against this source.
    """
    refs = {claim.evidence_id for claim in page.claims}
    refs.update(p.transaction_id for p in page.precedent_activity)
    refs.update(comp.evidence_id for comp in page.valuation_context.comps)
    refs.update(ref for risk in page.risk_flags for ref in risk.evidence_ids)
    if refs - index.keys():
        raise EvaluationError("Cited evidence is absent from the frozen source")
    lines = [_fact_text(index[ref]) for ref in sorted(refs)]
    lines.append("Code-computed ranking: " + pack.ranking.model_dump_json())
    return "\n".join(lines)
