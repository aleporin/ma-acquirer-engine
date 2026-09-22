"""Summarize judge quality with explicit coverage and buyer-clustered intervals.

Owns: Per-dimension rates, human calibration, and paired reviewer comparisons.
Does not own: Running providers, changing human labels, or inferring causal lift.
"""

from acquirer_engine.errors import EvaluationError
from evals.judges.calibration import Agreement, agreement
from evals.judges.plan import JudgePlan
from evals.judges.results import JudgeRun
from evals.judges.schema import Case, Dimension, IdentificationAnswer, Record, RubricAnswer, Vote


class Rate(Record):
    """Unknowns and failed requests never silently enter the binary denominator."""

    total: int
    answered: int
    passed: int
    unknown: int
    failed_requests: int
    pass_rate: float | None
    accuracy: float | None


class JudgeSummary(Record):
    """Calibration and page quality remain separate measured quantities."""

    corpus_digest: str
    plan_digest: str
    rubric: dict[str, dict[str, dict[str, Rate]]]
    identification: dict[str, dict[str, Rate]]
    human_agreement: dict[str, dict[str, Agreement]]
    judge_agreement: dict[str, Agreement]
    paired_reviewer_changes: dict[str, int]
    word_counts: dict[str, int]
    request_failures: int
    human_pages: int
    buyer_clusters: int
    cost_usd: float
    uncertain_cost_bound_usd: float


def _rate(votes: list[Vote | None]) -> Rate:
    known = sum(v in {"Pass", "Fail"} for v in votes)
    passed = votes.count("Pass")
    return Rate(
        total=len(votes),
        answered=sum(v is not None for v in votes),
        passed=passed,
        unknown=votes.count("Unknown"),
        failed_requests=votes.count(None),
        pass_rate=passed / known if known else None,
        accuracy=passed / len(votes) if votes else None,
    )


def _cohort(case: Case) -> str:
    return case.stage if case.reviewer_enabled else "reviewer_disabled"


def _votes(plan: JudgePlan, run: JudgeRun) -> dict[tuple[str, str, str], Vote]:
    if run.plan_digest != plan.digest:
        raise EvaluationError("Judge report does not match its plan")
    outcomes = {o.job_id: o for o in run.outcomes}
    if len(outcomes) != len(run.outcomes) or set(outcomes) != {j.job_id for j in plan.jobs}:
        raise EvaluationError("Judge outcome inventory is incomplete or duplicated")
    result: dict[tuple[str, str, str], Vote] = {}
    for job in plan.jobs:
        answer = outcomes[job.job_id].answer
        if isinstance(answer, RubricAnswer) and job.kind != "identification":
            vote = answer.vote
        elif isinstance(answer, IdentificationAnswer) and job.kind == "identification":
            if answer.choice is not None and answer.choice > len(job.candidate_order):
                raise EvaluationError("Identification choice exceeds the candidate inventory")
            vote = (
                "Unknown"
                if answer.choice is None
                else ("Pass" if answer.choice == job.expected_choice else "Fail")
            )
        elif answer is None:
            continue
        else:
            raise EvaluationError("Judge answer has the wrong output schema")
        result[(job.role, job.case_id, job.kind)] = vote
    return result


def _comparisons(
    plan: JudgePlan,
    left: dict[tuple[str, str], Vote],
    right: dict[tuple[str, str], Vote],
) -> dict[str, Agreement]:
    cases = {c.case_id: c for c in plan.corpus.cases if c.stage == "after_review"}
    result = {}
    for dimension in [*Dimension, "all"]:
        keys = sorted(
            k
            for k in left.keys() & right.keys()
            if k[0] in cases and (dimension == "all" or k[1] == dimension)
        )
        result[str(dimension)] = agreement(
            [left[k] for k in keys],
            [right[k] for k in keys],
            [cases[k[0]].buyer for k in keys],
            seed=plan.config.seed,
            samples=plan.config.bootstrap_samples,
            confidence=plan.config.confidence,
        )
    return result


def _paired_changes(plan: JudgePlan, votes: dict[tuple[str, str, str], Vote]) -> dict[str, int]:
    before = {
        (c.source_run_id, c.buyer): c for c in plan.corpus.cases if c.stage == "before_review"
    }
    after = [c for c in plan.corpus.cases if c.reviewer_enabled and c.stage == "after_review"]
    result: dict[str, int] = {}
    for role in plan.config.roles:
        for kind in [*Dimension, "identification"]:
            pairs = [
                (
                    votes.get((role, before[(c.source_run_id, c.buyer)].case_id, kind)),
                    votes.get((role, c.case_id, kind)),
                )
                for c in after
                if (c.source_run_id, c.buyer) in before
            ]
            known = [(a, b) for a, b in pairs if a in {"Pass", "Fail"} and b in {"Pass", "Fail"}]
            prefix = f"{role}_{kind}"
            result[prefix + "_compared"] = len(known)
            result[prefix + "_improved"] = sum(a == "Fail" and b == "Pass" for a, b in known)
            result[prefix + "_worsened"] = sum(a == "Pass" and b == "Fail" for a, b in known)
    return result


def _rates(
    plan: JudgePlan, votes: dict[tuple[str, str, str], Vote]
) -> tuple[dict[str, dict[str, dict[str, Rate]]], dict[str, dict[str, Rate]]]:
    cohorts = sorted({_cohort(c) for c in plan.corpus.cases})
    rubric = {
        cohort: {
            r: {
                str(d): _rate(
                    [
                        votes.get((r, c.case_id, d))
                        for c in plan.corpus.cases
                        if _cohort(c) == cohort
                    ]
                )
                for d in Dimension
            }
            for r in plan.config.roles
        }
        for cohort in cohorts
    }
    identification = {
        cohort: {
            r: _rate(
                [
                    votes.get((r, c.case_id, "identification"))
                    for c in plan.corpus.cases
                    if _cohort(c) == cohort
                ]
            )
            for r in plan.config.roles
        }
        for cohort in cohorts
    }
    return rubric, identification


def summarize(plan: JudgePlan, run: JudgeRun) -> JudgeSummary:
    """Report measured votes, excluding Unknown pairs from kappa explicitly.

    Args:
        plan, run: Sealed requests with human labels and corresponding outcomes.
    Returns:
        Rates and intervals with sample sizes, failures, and abstentions.
    Raises:
        EvaluationError: Outcomes do not cover the frozen request inventory.
    """
    votes = _votes(plan, run)
    by_role = {
        r: {(c, d): v for (role, c, d), v in votes.items() if role == r and d != "identification"}
        for r in plan.config.roles
    }
    human = {(label.case_id, str(label.dimension)): label.vote for label in plan.labels}
    rubric, identification = _rates(plan, votes)
    return JudgeSummary(
        corpus_digest=plan.corpus.digest,
        plan_digest=plan.digest,
        rubric=rubric,
        identification=identification,
        human_agreement={r: _comparisons(plan, by_role[r], human) for r in plan.config.roles},
        judge_agreement=_comparisons(
            plan, by_role[plan.config.roles[0]], by_role[plan.config.roles[1]]
        ),
        paired_reviewer_changes=_paired_changes(plan, votes),
        word_counts={c.case_id: len(c.page.split()) for c in plan.corpus.cases},
        request_failures=sum(o.error is not None for o in run.outcomes),
        human_pages=len({label.case_id for label in plan.labels}),
        buyer_clusters=len({c.buyer for c in plan.corpus.cases}),
        cost_usd=run.cost_usd,
        uncertain_cost_bound_usd=run.uncertain_cost_bound_usd,
    )
