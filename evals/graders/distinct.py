"""Measure lexical overlap between accepted rationale pages.

Owns: Pairwise word-ngram Jaccard similarity before portfolio review.
Does not own: Semantic quality or the later name-masked identification judge.
"""

import re
from itertools import combinations
from statistics import fmean

from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.settings import LayerSpec
from acquirer_engine.validation.schema import prose_sections
from evals.scorecard import LayerResult, Metric


def _ngrams(page: PageResult, width: int) -> set[tuple[str, ...]]:
    assert page.rationale is not None
    sections = prose_sections(page.rationale)
    sections.pop("reasoning")
    words = re.findall(r"\w+", " ".join(sections.values()).casefold())
    return {tuple(words[i : i + width]) for i in range(len(words) - width + 1)}


def _similarities(run: AnalystRun, width: int) -> list[float]:
    pages = [_ngrams(p, width) for p in run.pages if p.status == "verified" and p.rationale]
    return [len(a & b) / len(a | b) if a | b else 1 for a, b in combinations(pages, 2)]


def grade(
    layer: LayerSpec, runs: list[AnalystRun] | None = None, config: AnalystConfig | None = None
) -> LayerResult:
    """Measure overlap without inventing an uncalibrated pass threshold.

    Args:
        layer: Registered layer identity.
        runs: Recorded outputs, separated by execution mode.
        config: Configured ngram width.
    Returns:
        Measurements on verified-page pairs; absent pairs fail measurement.
    """
    if not runs or config is None:
        return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
    metrics = {}
    measured = True
    for mode in sorted({run.mode for run in runs}):
        group = [r for r in runs if r.mode == mode]
        values = [v for r in group for v in _similarities(r, config.distinct_ngram_words)]
        metrics[f"{mode}_page_pairs"] = Metric(value=len(values), direction="higher")
        if values:
            metrics[f"{mode}_mean_pairwise_jaccard"] = Metric(
                value=fmean(values), direction="lower"
            )
            metrics[f"{mode}_max_pairwise_jaccard"] = Metric(value=max(values), direction="lower")
        else:
            measured = False
    return LayerResult(
        id=layer.id,
        name=layer.name,
        selected=True,
        status="passed" if measured else "failed",
        metrics=metrics,
    )
