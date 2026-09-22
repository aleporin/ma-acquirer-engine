"""Specify isolated judgments, bounded requests, and zero-cost replay.

Owns: Real structured-output execution with offline function models.
Does not own: Live judge quality or provider credentials.
"""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from evals.judges.cases import seal_corpus
from evals.judges.config import load_judge_config
from evals.judges.plan import JudgePlan, build_plan
from evals.judges.runtime import execute, replay
from evals.judges.schema import Dimension, HumanLabel
from tests.evaluation.test_judge_cases import example_case


def plan_for_test(deps: Deps) -> JudgePlan:
    root = Path(__file__).resolve().parents[2]
    corpus = seal_corpus([example_case()], seed=7)
    labels = [
        HumanLabel(case_id=example_case().case_id, dimension=d, vote="Pass") for d in Dimension
    ]
    return build_plan(
        corpus,
        load_judge_config(root / "config/judges.yaml"),
        deps.settings.models,
        root / "prompts/judges",
        labels,
    )


def judge_model(calls: list[str], *, invalid: bool = False) -> FunctionModel:
    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(str(messages))
        schema = info.output_tools[0].parameters_json_schema
        answer: dict[str, object] = {
            "reason": "The supplied evidence supports the requested criterion."
        }
        if "choice" in schema["properties"]:
            answer["choice"] = 999 if invalid else 1
        else:
            answer["vote"] = "wrong" if invalid else "Pass"
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, answer)],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
        )

    return FunctionModel(respond)


@pytest.mark.asyncio
async def test_each_model_grades_each_dimension_in_an_isolated_request(
    tmp_path: Path,
    deps: Deps,
) -> None:
    plan = plan_for_test(deps)
    calls: list[str] = []
    models = {role: judge_model(calls) for role in plan.config.roles}
    report = await execute(plan, tmp_path / "original", models, deps.logger, mode="test")
    assert len(calls) == 12 and len(report.outcomes) == 12
    assert all(outcome.error is None for outcome in report.outcomes)
    assert all("human_labels" not in call for call in calls)
    assert all(len(outcome.calls) == 1 for outcome in report.outcomes)
    assert (tmp_path / "original/trace.jsonl").exists()
    result = await replay(tmp_path / "original", tmp_path / "replay", deps.logger)
    assert [outcome.answer for outcome in result.outcomes] == [o.answer for o in report.outcomes]
    assert len(calls) == 12 and result.cost_usd == 0


@pytest.mark.asyncio
async def test_invalid_votes_and_out_of_range_choices_do_not_become_unknown(
    tmp_path: Path,
    deps: Deps,
) -> None:
    plan = plan_for_test(deps)
    calls: list[str] = []
    report = await execute(
        plan,
        tmp_path / "run",
        {role: judge_model(calls, invalid=True) for role in plan.config.roles},
        deps.logger,
        mode="test",
    )
    assert len(calls) == 12
    assert all(o.error and o.answer is None for o in report.outcomes)
    result = await replay(tmp_path / "run", tmp_path / "replay", deps.logger)
    assert [o.error for o in result.outcomes] == [o.error for o in report.outcomes]


@pytest.mark.asyncio
async def test_content_identical_paired_pages_reuse_the_same_judgment(
    tmp_path: Path,
    deps: Deps,
) -> None:
    plan = plan_for_test(deps)
    original = plan.corpus.cases[0]
    before = original.model_copy(update={"stage": "before_review", "case_id": "case-" + "f" * 16})
    root = Path(__file__).resolve().parents[2]
    plan = build_plan(
        seal_corpus([original, before], seed=7),
        plan.config,
        deps.settings.models,
        root / "prompts/judges",
        list(plan.labels),
    )
    calls: list[str] = []
    result = await execute(
        plan,
        tmp_path / "run",
        {role: judge_model(calls) for role in plan.config.roles},
        deps.logger,
        mode="test",
    )
    assert len(result.outcomes) == 24 and len(calls) == 12
    assert sum(outcome.cache_hit for outcome in result.outcomes) == 12


@pytest.mark.asyncio
async def test_changed_plan_or_missing_replay_response_never_calls_a_provider(
    tmp_path: Path,
    deps: Deps,
) -> None:
    plan = plan_for_test(deps)
    calls: list[str] = []
    await execute(
        plan,
        tmp_path / "run",
        {role: judge_model(calls) for role in plan.config.roles},
        deps.logger,
        mode="test",
    )
    next((tmp_path / "run/responses").glob("*.json")).unlink()
    result = await replay(tmp_path / "run", tmp_path / "replay", deps.logger)
    assert any(outcome.error for outcome in result.outcomes)
    assert len(calls) == 12 and result.cost_usd == 0
    trace = [
        json.loads(line) for line in (tmp_path / "replay/trace.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "judge_failed" for event in trace)
