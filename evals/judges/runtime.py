"""Execute isolated judge jobs and replay frozen responses without credentials.

Owns: Task scheduling, structured verdict validation, and run archives.
Does not own: Client construction, calibration metrics, or human labeling.
"""

import asyncio
import shutil
from collections.abc import Mapping
from pathlib import Path

from google.genai.types import ThinkingLevel
from pydantic import JsonValue, RootModel, ValidationError
from pydantic_ai import Agent, ToolOutput
from pydantic_ai.exceptions import AgentRunError, ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModelSettings
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits
from structlog.stdlib import BoundLogger

from acquirer_engine.errors import AcquirerEngineError, EvaluationError
from acquirer_engine.llm.cache import ResponseCache
from acquirer_engine.llm.cost import CostLedger, ExecutionMode, RunBudget
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.trace import TraceWriter
from evals.judges.plan import Job, JudgePlan, output_schemas
from evals.judges.recording import JudgeDeps, RecordedJudge
from evals.judges.results import JudgeRun, Outcome
from evals.judges.schema import IdentificationAnswer, RubricAnswer


def _settings(deps: JudgeDeps, job: Job) -> ModelSettings:
    config = deps.plan.config
    if deps.plan.models[job.role].provider == "openai":
        return OpenAIResponsesModelSettings(
            max_tokens=config.max_output_tokens,
            openai_reasoning_effort=config.openai_reasoning_effort,
            openai_store=False,
        )
    return GoogleModelSettings(
        max_tokens=config.max_output_tokens,
        google_thinking_config={"thinking_level": ThinkingLevel(config.google_thinking_level)},
    )


async def _answer(
    deps: JudgeDeps, job: Job, model: RecordedJudge
) -> RubricAnswer | IdentificationAnswer:
    payload = data_block("judge_material", RootModel[JsonValue].model_validate_json(job.payload))
    schema: type[IdentificationAnswer] | type[RubricAnswer] = (
        IdentificationAnswer if job.kind == "identification" else RubricAnswer
    )
    output: ToolOutput[RubricAnswer | IdentificationAnswer] = ToolOutput(schema, strict=True)
    agent = Agent(
        model,
        output_type=output,
        instructions=job.prompt,
        model_settings=_settings(deps, job),
        retries=0,
    )
    result = await agent.run(payload, usage_limits=UsageLimits(request_limit=1))
    answer = result.output
    if (
        isinstance(answer, IdentificationAnswer)
        and answer.choice is not None
        and answer.choice > len(job.candidate_order)
    ):
        raise EvaluationError("Identification choice exceeds the candidate inventory")
    return answer


async def _run_job(deps: JudgeDeps, job: Job) -> Outcome:
    model = RecordedJudge(deps, job)
    seconds = None if deps.mode == "replay" else deps.plan.config.run_timeout_seconds
    try:
        async with asyncio.timeout(seconds), deps.semaphore:
            answer = await _answer(deps, job, model)
        outcome = Outcome(
            job_id=job.job_id, answer=answer, cache_hit=model.cache_hit, calls=tuple(model.calls)
        )
    except (
        AcquirerEngineError,
        AgentRunError,
        ModelAPIError,
        TimeoutError,
        ValidationError,
        OSError,
    ) as error:
        # Provider messages can contain request material; retain only safe failure identity.
        name = type(error).__name__
        outcome = Outcome(
            job_id=job.job_id, error=name, cache_hit=model.cache_hit, calls=tuple(model.calls)
        )
        deps.logger.warning("judge_failed", job_id=job.job_id, error=name)
    deps.trace.write(
        "judge_failed" if outcome.error else "judge_completed", job.case_id, outcome=outcome
    )
    return outcome


async def _scheduled_job(deps: JudgeDeps, job: Job, failures: Mapping[str, Outcome]) -> Outcome:
    if job.job_id not in failures:
        return await _run_job(deps, job)
    outcome = failures[job.job_id].model_copy(update={"calls": (), "cache_hit": False})
    deps.trace.write("judge_failed", job.case_id, outcome=outcome, recorded_failure=True)
    return outcome


def _write_plan(plan: JudgePlan, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if any(p.name != "log.jsonl" for p in directory.iterdir()):
        raise EvaluationError("Judge archive already exists")
    with (directory / "plan.json").open("x") as stream:
        stream.write(plan.model_dump_json(indent=2) + "\n")


def _resources(
    plan: JudgePlan,
    directory: Path,
    models: Mapping[str, Model],
    logger: BoundLogger,
    mode: ExecutionMode,
    cache_root: Path | None,
) -> JudgeDeps:
    return JudgeDeps(
        plan,
        dict(models),
        ResponseCache(cache_root or directory / "responses"),
        CostLedger(next(iter(plan.models.values()))),
        RunBudget(plan.config.max_run_usd),
        TraceWriter(directory / "trace.jsonl"),
        logger,
        mode,
        asyncio.Semaphore(plan.config.concurrency),
    )


async def execute(
    plan: JudgePlan,
    directory: Path,
    models: Mapping[str, Model],
    logger: BoundLogger,
    *,
    mode: ExecutionMode = "live",
    cache_root: Path | None = None,
    git_sha: str | None = None,
    source_dirty: bool = False,
    recorded_failures: Mapping[str, Outcome] | None = None,
) -> JudgeRun:
    """Execute a frozen plan with one shared budget and no validation retries.

    Args:
        plan, directory: Frozen requests and a new immutable archive directory.
        models, logger: Provider models built once at the command boundary and logger.
        mode, cache_root, git_sha, source_dirty: Execution, replay, and source provenance.
    Returns:
        Every job's verdict or explicit failure, preserving returned usage.
    Raises:
        EvaluationError: Output schemas changed or required models are absent.
    """
    if plan.output_schemas != output_schemas():
        raise EvaluationError("Judge output schema changed; use the original evaluator")
    if mode != "replay" and set(models) != set(plan.config.roles):
        raise EvaluationError("Every configured judge must be injected")
    _write_plan(plan, directory)
    deps = _resources(plan, directory, models, logger, mode, cache_root)
    outcomes = await asyncio.gather(
        *(_scheduled_job(deps, job, recorded_failures or {}) for job in plan.jobs)
    )
    result = JudgeRun(
        plan_digest=plan.digest,
        mode=mode,
        observation_mode=mode,
        outcomes=tuple(outcomes),
        uncertain_cost_bound_usd=deps.budget.uncertain,
        git_sha=git_sha,
        source_dirty=source_dirty,
    )
    (directory / "run.json").write_text(result.model_dump_json(indent=2) + "\n")
    return result


async def replay(source: Path, destination: Path, logger: BoundLogger) -> JudgeRun:
    """Revalidate original responses without constructing a provider client.

    Args:
        source, destination: Original archive and a new output directory.
        logger: Injected run logger.
    Returns:
        Replayed verdicts, with missing responses reported as failures.
    Raises:
        EvaluationError: Plan integrity or archived job inventory does not match.
    """
    plan = JudgePlan.model_validate_json((source / "plan.json").read_bytes())
    original = JudgeRun.model_validate_json((source / "run.json").read_bytes())
    if original.plan_digest != plan.digest or [o.job_id for o in original.outcomes] != [
        j.job_id for j in plan.jobs
    ]:
        raise EvaluationError("Judge archive does not match its sealed plan")
    result = await execute(
        plan,
        destination,
        {},
        logger,
        mode="replay",
        cache_root=source / "responses",
        recorded_failures={o.job_id: o for o in original.outcomes if o.error and not o.calls},
    )
    result = result.model_copy(
        update={"observation_mode": original.observation_mode or original.mode}
    )
    (destination / "run.json").write_text(result.model_dump_json(indent=2) + "\n")
    if (source / "responses").exists():
        shutil.copytree(source / "responses", destination / "responses")
    return result
