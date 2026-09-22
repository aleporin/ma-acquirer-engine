"""Select weight hypotheses chronologically, then measure a frozen choice.

Owns: Selection folds, identical candidate universes, and exploratory comparisons.
Does not own: Changing production weights or claiming an untouched benchmark.
"""

import hashlib
from collections.abc import Sequence
from statistics import fmean

from pydantic import BaseModel, ConfigDict

from acquirer_engine.data import Transaction
from acquirer_engine.errors import EvaluationError
from acquirer_engine.ranking.config import RankingConfig
from acquirer_engine.ranking.features import FittedFeatures, fit_features
from acquirer_engine.ranking.scorer import RankedAcquirer, rank_acquirers
from evals.ranking.backtest import target_from_transaction
from evals.ranking.baselines import baseline_rankings
from evals.ranking.metrics import Interval, metrics_at_rank, paired_lift
from evals.ranking.report import CaseResult
from evals.ranking.weighting import (
    Candidate,
    ExperimentPolicy,
    buyer_weights,
    shared_candidate,
    validate_proposals,
)


class Variant(BaseModel):
    """One complete type hypothesis with an optional conservative buyer tilt."""

    model_config = ConfigDict(frozen=True)
    candidate: Candidate
    strength: float

    @property
    def key(self) -> str:
        """Distinguish type-only and buyer-adjusted trials without changing names."""
        return f"buyer:{self.candidate.name}" if self.strength else self.candidate.name


class Period(BaseModel):
    """Auditable chronological fit and complete query population."""

    train_end_year: int
    training_sha256: str
    eligible_train_rows: int
    candidate_count: int
    test_rows: int
    unseen_labels: int
    metrics: dict[str, dict[str, float]]
    cases: list[CaseResult]


class Selection(BaseModel):
    """All selection trials and the choice frozen before benchmark evaluation."""

    folds: list[Period]
    trials: dict[str, dict[str, float]]
    type_winner: str
    buyer_winner: str
    selected: str


class ExperimentReport(BaseModel):
    """Exploratory results retain the complete search and uncertainty policy."""

    exploratory: bool = True
    top_k: int
    policy: ExperimentPolicy
    candidates: list[Candidate]
    selection: Selection
    benchmark: Period
    lift: dict[str, dict[str, Interval]]


def variants(
    candidates: list[Candidate], scoring: RankingConfig, policy: ExperimentPolicy
) -> list[Variant]:
    """Include the unchanged control and predeclared buyer adjustment for every profile."""
    validate_proposals(candidates, policy, scoring)
    return [
        Variant(candidate=candidate, strength=strength)
        for candidate in [shared_candidate(scoring), *sorted(candidates, key=lambda c: c.name)]
        for strength in (0, policy.buyer_strength)
    ]


def rerank(
    ranked: list[RankedAcquirer],
    fitted: FittedFeatures,
    variant: Variant,
    scoring: RankingConfig,
    policy: ExperimentPolicy,
) -> list[str]:
    """Reuse production feature signals while changing only final feature weights."""
    scores = {}
    for item in ranked:
        weights = buyer_weights(
            variant.candidate,
            fitted.acquirers[item.acquirer],
            scoring,
            policy,
            strength=variant.strength,
        )
        scores[item.acquirer] = sum(
            weights[name] * item.signals[name].posterior for name in sorted(weights)
        )
    return sorted(scores, key=lambda name: (-scores[name], name.casefold(), name))


def means(cases: list[CaseResult], k: int) -> dict[str, dict[str, float]]:
    """Average every query, including labels absent from training candidates."""
    if not cases:
        raise EvaluationError("Every experiment period requires test observations")
    values = {
        name: [metrics_at_rank(case.ranks[name], k) for case in cases] for name in cases[0].ranks
    }
    return {
        name: {metric: fmean(row[metric] for row in rows) for metric in rows[0]}
        for name, rows in values.items()
    }


def _case(
    row: Transaction,
    fitted: FittedFeatures,
    trials: list[Variant],
    scoring: RankingConfig,
    policy: ExperimentPolicy,
) -> CaseResult:
    target = target_from_transaction(row)
    ranked = rank_acquirers(fitted, target, scoring)
    rankings = baseline_rankings(
        fitted, target.sector, seed=policy.seed, query_id=row.transaction_id
    )
    rankings.update({v.key: rerank(ranked, fitted, v, scoring, policy) for v in trials})
    return CaseResult(
        transaction_id=row.transaction_id,
        ranks={
            name: buyers.index(row.acquirer) + 1 if row.acquirer in buyers else None
            for name, buyers in rankings.items()
        },
    )


def measure_period(
    rows: Sequence[Transaction],
    train_end: int,
    test_end: int,
    trials: list[Variant],
    scoring: RankingConfig,
    policy: ExperimentPolicy,
) -> Period:
    """Fit strictly before each period and retain cold starts as misses."""
    ordered = sorted(rows, key=lambda row: row.transaction_id)
    train = [row for row in ordered if row.deal_year <= train_end]
    test = [row for row in ordered if train_end < row.deal_year <= test_end]
    fitted = fit_features(train, scoring, reference_year=train_end)
    cases = [_case(row, fitted, trials, scoring, policy) for row in test]
    encoded = "\n".join(
        row.model_dump_json() for row in train if row.transaction_id in fitted.training_ids
    ).encode()
    return Period(
        train_end_year=train_end,
        training_sha256=hashlib.sha256(encoded).hexdigest(),
        eligible_train_rows=len(fitted.training_ids),
        candidate_count=len(fitted.acquirers),
        test_rows=len(test),
        unseen_labels=sum(row.acquirer not in fitted.acquirers for row in test),
        metrics=means(cases, scoring.top_k),
        cases=cases,
    )


def select_candidates(
    rows: Sequence[Transaction],
    candidates: list[Candidate],
    scoring: RankingConfig,
    policy: ExperimentPolicy,
) -> Selection:
    """Select by pooled recall, then MRR, then simpler control and lexical name.

    The function never reads benchmark rows. Every selection year trains on
    earlier years only; no year is used as both feature history and its own test.
    """
    trials = variants(candidates, scoring, policy)
    folds = [
        measure_period(rows, y - 1, y, trials, scoring, policy) for y in policy.selection_years
    ]
    metrics = means([case for fold in folds for case in fold.cases], scoring.top_k)

    def objective(variant: Variant) -> tuple[float, float, bool, bool, str]:
        values = metrics[variant.key]
        return (
            -values["recall_at_k"],
            -values["mrr"],
            bool(variant.strength),
            variant.candidate.name != "shared",
            variant.key,
        )

    return Selection(
        folds=folds,
        trials={v.key: metrics[v.key] for v in trials},
        type_winner=min((v for v in trials if not v.strength), key=objective).key,
        buyer_winner=min((v for v in trials if v.strength), key=objective).key,
        selected=min(trials, key=objective).key,
    )


def run_experiment(
    rows: Sequence[Transaction],
    candidates: list[Candidate],
    scoring: RankingConfig,
    policy: ExperimentPolicy,
) -> ExperimentReport:
    """Freeze the selection, measure known later data, and report paired uncertainty."""
    selection = select_candidates(rows, candidates, scoring, policy)
    keys = {"shared", selection.type_winner, selection.buyer_winner, selection.selected}
    trials = [v for v in variants(candidates, scoring, policy) if v.key in keys]
    benchmark = measure_period(
        rows, policy.selection_years[-1], policy.test_end_year, trials, scoring, policy
    )
    values = {
        name: [metrics_at_rank(case.ranks[name], scoring.top_k) for case in benchmark.cases]
        for name in benchmark.metrics
    }
    lift = {
        baseline: {
            metric: paired_lift(
                [row[metric] for row in values[selection.selected]],
                [row[metric] for row in values[baseline]],
                seed=policy.seed,
                samples=policy.bootstrap_samples,
                confidence=policy.confidence,
            )
            for metric in benchmark.metrics[baseline]
        }
        for baseline in ("shared", "global_popularity", "sector_popularity", "random")
    }
    return ExperimentReport(
        top_k=scoring.top_k,
        policy=policy,
        candidates=candidates,
        selection=selection,
        benchmark=benchmark,
        lift=lift,
    )
