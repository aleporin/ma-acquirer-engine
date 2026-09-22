"""Specify accounting and replay for unsuccessful judge requests.

Owns: Budget denial, unknown billed usage, and sealed-plan integrity tests.
Does not own: Retrying providers or treating failures as abstentions.
"""

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from evals.judges.runtime import execute, replay
from tests.evaluation.test_judge_runner import judge_model, plan_for_test


@pytest.mark.asyncio
async def test_budget_denial_makes_no_provider_call_and_replays_as_denial(
    tmp_path: Path, deps: Deps
) -> None:
    plan = plan_for_test(deps)
    plan = plan.model_copy(
        update={"config": plan.config.model_copy(update={"max_run_usd": 0.000001})}
    )
    calls: list[str] = []
    run = await execute(
        plan,
        tmp_path / "run",
        {role: judge_model(calls) for role in plan.config.roles},
        deps.logger,
        mode="live",
    )
    assert calls == [] and all(o.error == "BudgetExceeded" for o in run.outcomes)
    assert run.uncertain_cost_bound_usd == 0
    result = await replay(tmp_path / "run", tmp_path / "replay", deps.logger)
    assert [o.error for o in result.outcomes] == [o.error for o in run.outcomes]
    assert result.cost_usd == 0 and result.observation_mode == "live"


@pytest.mark.asyncio
async def test_provider_failure_retains_uncertain_cost_and_does_not_retry(
    tmp_path: Path, deps: Deps
) -> None:
    calls: list[int] = []

    async def fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        raise TimeoutError("simulated timeout")

    plan = plan_for_test(deps)
    run = await execute(
        plan,
        tmp_path / "run",
        {role: FunctionModel(fail) for role in plan.config.roles},
        deps.logger,
        mode="live",
    )
    assert len(calls) == 12 and all(o.error == "TimeoutError" for o in run.outcomes)
    assert run.cost_usd == 0 and run.uncertain_cost_bound_usd > 0
    result = await replay(tmp_path / "run", tmp_path / "replay", deps.logger)
    assert all(o.error == "TimeoutError" for o in result.outcomes)
    assert len(calls) == 12 and result.uncertain_cost_bound_usd == 0


@pytest.mark.asyncio
async def test_replay_rejects_an_edited_plan_before_using_cached_verdicts(
    tmp_path: Path, deps: Deps
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
    path = tmp_path / "run/plan.json"
    changed = plan.model_copy(update={"jobs": plan.jobs[:-1]})
    path.write_text(changed.model_dump_json())
    with pytest.raises(EvaluationError, match="sealed plan"):
        await replay(tmp_path / "run", tmp_path / "replay", deps.logger)
    assert len(calls) == 12
