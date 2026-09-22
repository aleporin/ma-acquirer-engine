"""Prepare the blind calibration cohort from immutable generation archives.

Owns: Matched cohort checks and publication of the local reading packet.
Does not own: Human labels, provider calls, or judge verdicts.
"""

from pathlib import Path

from acquirer_engine.errors import EvaluationError
from evals.judges.cases import seal_corpus
from evals.judges.config import JudgeConfig
from evals.judges.labels import export_packet
from evals.judges.schema import Corpus
from evals.judges.sources import load_cases


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
