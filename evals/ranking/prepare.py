"""Prepare ranking, data-quality, and stability evaluation artifacts.

Owns: Data/ranking evaluation composition and reproducible result snapshots.
Does not own: File publication, provider calls, or tuning on evaluation outcomes.
"""

import json
from collections.abc import Sequence
from functools import partial

from acquirer_engine.data.quality import quality_report
from acquirer_engine.data.schema import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.ranking.scorer import RankedAcquirer, rank_acquirers
from acquirer_engine.ranking.target import assignment_target
from evals.graders import backtest, stability
from evals.harness import PreparedEvaluation
from evals.ranking.backtest import run_backtest
from evals.scorecard import LayerResult


def _rank_repeatedly(rows: Sequence[Transaction], deps: Deps) -> list[list[RankedAcquirer]]:
    config = deps.settings.scoring
    runs = []
    for _ in range(deps.settings.evaluation.backtest.stability_runs):
        fitted = fit_features(rows, config, reference_year=config.reference_year)
        history = [row for buyer in fitted.acquirers.values() for row in buyer.rows]
        target = assignment_target(history, config)
        runs.append(rank_acquirers(fitted, target, config)[: config.top_k])
    return runs


def _stability(runs: list[list[RankedAcquirer]], minimum: int) -> stability.RankingStability:
    names = [[item.acquirer for item in run] for run in runs]
    levels = [[item.conviction for item in run] for run in runs]
    return stability.RankingStability(
        identity=sum(run == names[0] for run in names) / len(names),
        conviction_agreement=sum(run == levels[0] for run in levels) / len(levels),
        levels=len(set(levels[0])),
        minimum_levels=minimum,
    )


def prepare_ranking(
    rows: Sequence[Transaction], deps: Deps, unit_result: LayerResult
) -> PreparedEvaluation:
    """Compose measured graders while retaining all observations and artifacts.

    Args:
        rows: Validated input dataset.
        deps: One shared settings and logger snapshot.
        unit_result: Layer result from actual isolated test execution.
    Returns:
        Pure grader closures and JSON companion artifacts.
    """
    config = deps.settings.scoring
    evaluation = deps.settings.evaluation
    quality = quality_report(
        rows, multiple_tolerance=config.multiple_tolerance, margin_tolerance=config.margin_tolerance
    )
    report = run_backtest(rows, config, evaluation.backtest, seed=evaluation.seed)
    runs = _rank_repeatedly(rows, deps)
    agreement = _stability(runs, evaluation.backtest.minimum_conviction_levels)
    deps.logger.info("data_quality_measured", stage="eval", **quality.model_dump())
    deps.logger.info(
        "ranking_computed", stage="eval", candidates=len(runs[0]), levels=agreement.levels
    )
    snapshot = {
        "stability_runs": len(runs),
        "acquirers": [item.model_dump(mode="json") for item in runs[0]],
        "top_k_identity": agreement.identity,
        "conviction_agreement": agreement.conviction_agreement,
    }
    return PreparedEvaluation(
        graders={
            0: lambda layer: unit_result,
            1: partial(backtest.grade, report=report),
            5: partial(stability.grade, report=agreement),
        },
        artifacts={
            "backtest.json": report.model_dump_json(indent=2) + "\n",
            "data_quality.json": quality.model_dump_json(indent=2) + "\n",
            "top10.json": json.dumps(snapshot, indent=2) + "\n",
        },
    )
