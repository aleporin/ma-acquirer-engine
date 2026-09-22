"""Specify offline ingestion of calibrated judge observations.

Owns: Layer three/four integration and refusal of synthetic quality evidence.
Does not own: Paid execution or changing earlier layer measurements.
"""

from pathlib import Path

from acquirer_engine.deps import Deps
from evals.judges.cases import seal_corpus
from evals.judges.plan import JudgePlan, build_plan
from evals.judges.results import JudgeRun, Outcome
from evals.judges.schema import Dimension, HumanLabel, IdentificationAnswer, RubricAnswer
from evals.phase1 import PreparedEvaluation
from evals.phase5 import prepare_phase5
from tests.evaluation.test_judge_cases import example_case
from tests.evaluation.test_judge_runner import plan_for_test


def matched_plan(deps: Deps) -> JudgePlan:
    prototype = plan_for_test(deps)
    cases = []
    labels = []
    for source in range(2):
        for buyer in range(2):
            index = source * 2 + buyer + 1
            case = example_case(index).model_copy(
                update={
                    "buyer": "Buyer A" if buyer == 0 else "Buyer B",
                    "source_run_id": f"{source + 1:032x}",
                    "reviewer_enabled": source == 0,
                }
            )
            cases.append(case)
            labels.extend(
                HumanLabel(case_id=case.case_id, dimension=d, vote="Pass" if buyer == 0 else "Fail")
                for d in Dimension
            )
            if source == 0:
                cases.append(
                    case.model_copy(
                        update={"stage": "before_review", "case_id": f"case-{index + 10:016x}"}
                    )
                )
    return build_plan(
        seal_corpus(cases, seed=7),
        prototype.config.model_copy(update={"candidate_count": 2}),
        deps.settings.models,
        Path(__file__).resolve().parents[2] / "prompts/judges",
        labels,
    )


def write_observation(path: Path, deps: Deps, *, synthetic: bool = False) -> None:
    plan = matched_plan(deps)
    votes = {c.case_id: ("Pass" if c.buyer == "Buyer A" else "Fail") for c in plan.corpus.cases}
    outcomes = tuple(
        Outcome(
            job_id=j.job_id,
            answer=(
                IdentificationAnswer(choice=j.expected_choice, reason="Matching facts")
                if j.kind == "identification"
                else RubricAnswer.model_validate(
                    {"vote": votes[j.case_id], "reason": "Specific facts"}
                )
            ),
        )
        for j in plan.jobs
    )
    run = JudgeRun(
        plan_digest=plan.digest,
        mode="test" if synthetic else "live",
        outcomes=outcomes,
        git_sha="a" * 40,
        uncertain_cost_bound_usd=0,
    )
    path.mkdir()
    (path / "plan.json").write_text(plan.model_dump_json())
    (path / "run.json").write_text(run.model_dump_json())


def test_judge_observations_add_identification_and_calibration_offline(
    tmp_path: Path, deps: Deps
) -> None:
    write_observation(tmp_path / "judges", deps)
    prepared = prepare_phase5(PreparedEvaluation({}, {}), tmp_path / "judges")
    layers = {layer.id: layer for layer in deps.settings.evaluation.layers}
    quality = prepared.graders[4](layers[4])
    assert quality.status == "passed"
    assert quality.metrics["judge_a_kappa"].value == 1
    distinct = prepared.graders[3](layers[3])
    assert distinct.status == "passed"
    assert distinct.metrics["reviewer_disabled_judge_a_identification_accuracy"].value == 1
    assert (
        "judge_summary.json" in prepared.artifacts and "judge_manifest.json" in prepared.artifacts
    )


def test_synthetic_outputs_cannot_pass_live_quality_gates(tmp_path: Path, deps: Deps) -> None:
    write_observation(tmp_path / "judges", deps, synthetic=True)
    prepared = prepare_phase5(PreparedEvaluation({}, {}), tmp_path / "judges")
    layer = next(layer for layer in deps.settings.evaluation.layers if layer.id == 4)
    assert prepared.graders[4](layer).status == "failed"
