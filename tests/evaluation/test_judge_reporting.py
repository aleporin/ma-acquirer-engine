"""Specify honest calibration, independent comparisons, and reviewer effects.

Owns: Report support, abstention, failure, and repeated-buyer boundaries.
Does not own: Provider behavior or live quality claims.
"""

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from evals.judges.reporting import summarize
from evals.judges.results import JudgeRun, Outcome
from evals.judges.schema import IdentificationAnswer, RubricAnswer, Vote
from tests.evaluation.test_judge_runner import plan_for_test


def test_report_separates_failures_abstentions_and_human_agreement(deps: Deps) -> None:
    plan = plan_for_test(deps)
    outcomes = []
    for job in plan.jobs:
        if job.kind == "identification":
            answer = IdentificationAnswer(choice=job.expected_choice, reason="Matching evidence")
            outcomes.append(Outcome(job_id=job.job_id, answer=answer))
        elif job.kind == "specificity" and job.role == plan.config.roles[0]:
            outcomes.append(Outcome(job_id=job.job_id, error="TimeoutError"))
        else:
            vote: Vote = "Unknown" if job.kind == "banker_tone" else "Pass"
            outcomes.append(
                Outcome(job_id=job.job_id, answer=RubricAnswer(vote=vote, reason="Evidence"))
            )
    run = JudgeRun(
        plan_digest=plan.digest, mode="test", outcomes=tuple(outcomes), uncertain_cost_bound_usd=0
    )
    report = summarize(plan, run)
    rate = report.rubric["reviewer_disabled"][plan.config.roles[0]]["specificity"]
    assert rate.total == 1 and rate.failed_requests == 1 and rate.unknown == 0
    assert rate.pass_rate is None
    assert report.human_agreement[plan.config.roles[0]]["all"].compared == 3
    assert report.human_agreement[plan.config.roles[0]]["all"].abstentions == 1
    assert report.judge_agreement["all"].compared == 3
    assert report.identification["reviewer_disabled"][plan.config.roles[0]].accuracy == 1
    assert report.word_counts[plan.corpus.cases[0].case_id] > 0
    assert report.request_failures == 1


def test_missing_or_foreign_outcomes_cannot_be_reported_as_complete(deps: Deps) -> None:
    plan = plan_for_test(deps)
    run = JudgeRun(plan_digest=plan.digest, mode="test", outcomes=(), uncertain_cost_bound_usd=0)
    with pytest.raises(EvaluationError, match="inventory"):
        summarize(plan, run)
    with pytest.raises(EvaluationError, match="plan"):
        summarize(plan, run.model_copy(update={"plan_digest": "wrong"}))
