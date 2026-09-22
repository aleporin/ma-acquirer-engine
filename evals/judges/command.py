"""Expose blind packet preparation, cost planning, judging, and replay.

Owns: CLI boundaries and construction of per-run resources.
Does not own: Generating new pages or choosing human votes.
"""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from google import genai
from google.genai.types import HttpOptions, HttpRetryOptions
from openai import AsyncOpenAI
from pydantic import ValidationError
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from structlog.stdlib import BoundLogger

from acquirer_engine.errors import AcquirerEngineError, ConfigError, EvaluationError
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.replay import git_state
from acquirer_engine.settings import load_settings
from evals.judges.config import load_judge_config
from evals.judges.labels import read_labels
from evals.judges.plan import JudgePlan, build_plan, estimate_plan
from evals.judges.prepare import prepare, validate_cohort
from evals.judges.reporting import summarize
from evals.judges.runtime import execute, replay
from evals.judges.schema import Corpus, JudgeRun


def _plan(root: Path, fresh: bool) -> JudgePlan:
    corpus = Corpus.model_validate_json((root / "evals/cases/p5-calibration.json").read_bytes())
    config = load_judge_config(root / "config/judges.yaml")
    labels = read_labels(root / "evals/labels/human_labels.csv", corpus) if fresh else []
    if fresh:
        validate_cohort(corpus, config)
    return build_plan(
        corpus, config, load_settings(root / "config").models, root / "prompts/judges", labels
    )


@asynccontextmanager
async def clients(plan: JudgePlan) -> AsyncIterator[dict[str, Model]]:
    """Construct each provider once, only after explicit fresh execution is selected.

    Args:
        plan: Frozen identities, limits, and SDK retry policy.
    Yields:
        Both independent judge models sharing their respective provider clients.
    Raises:
        ConfigError: Required environment variables are absent.
    """
    if not all(os.environ.get(key) for key in ("OPENAI_API_KEY", "GEMINI_API_KEY")):
        raise ConfigError("Fresh judging requires OPENAI_API_KEY and GEMINI_API_KEY")
    config = plan.config
    with genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=HttpOptions(
            timeout=int(config.request_timeout_seconds * 1000),
            retry_options=HttpRetryOptions(attempts=config.sdk_retries + 1),
        ),
    ) as google:
        async with (
            google.aio,
            AsyncOpenAI(
                max_retries=config.sdk_retries, timeout=config.request_timeout_seconds
            ) as openai,
        ):
            models: dict[str, Model] = {}
            for role, spec in plan.models.items():
                models[role] = (
                    OpenAIResponsesModel(
                        spec.model_id, provider=OpenAIProvider(openai_client=openai)
                    )
                    if spec.provider == "openai"
                    else GoogleModel(spec.model_id, provider=GoogleProvider(client=google))
                )
            yield models


async def _fresh(plan: JudgePlan, directory: Path, logger: BoundLogger, sha: str) -> JudgeRun:
    async with clients(plan) as models:
        return await execute(plan, directory, models, logger, git_sha=sha)


def _run(root: Path, plan: JudgePlan | None, source: Path | None) -> None:
    sha, dirty = git_state(root)
    if source is None and dirty:
        raise EvaluationError("Commit source changes before a measured fresh judge run")
    identity = uuid4().hex
    directory = root / "runs" / identity
    version = plan.config.version if plan else "judge_replay"
    with run_logger(
        root / "runs", identity, sha, version, sys.stderr, mode="replay" if source else "live"
    ) as logger:
        if source:
            result = asyncio.run(replay(source, directory, logger))
            plan = JudgePlan.model_validate_json((directory / "plan.json").read_bytes())
        else:
            assert plan is not None
            result = asyncio.run(_fresh(plan, directory, logger, sha))
    report = summarize(plan, result)
    (directory / "summary.json").write_text(report.model_dump_json(indent=2) + "\n")
    typer.echo(f"Judge run: {directory}")
    typer.echo(f"Answered: {len(result.outcomes) - report.request_failures}/{len(result.outcomes)}")
    typer.echo(
        f"Recorded cost: ${result.cost_usd:.6f}; "
        f"uncertain bound: ${result.uncertain_cost_bound_usd:.6f}"
    )
    if report.request_failures:
        raise typer.Exit(1)


def eval_judges(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    fresh: Annotated[
        bool, typer.Option(help="Permit paid calls after blind labels are complete.")
    ] = False,
    replay_from: Annotated[
        Path | None, typer.Option(help="Replay a saved judge directory for free.")
    ] = None,
) -> None:
    """Default to a free cost plan; require an explicit mode to execute judgments.

    Args:
        project: Repository containing corpus, labels, judge prompts, and configuration.
        fresh: Explicit paid execution; never combined with replay_from.
        replay_from: Original judge archive; does not read credentials or current prompts.
    Raises:
        typer.Exit: Inputs are incomplete, contradictory, or a judgment failed.
    """
    if fresh and replay_from:
        typer.echo("--fresh and --replay-from are mutually exclusive", err=True)
        raise typer.Exit(2)
    try:
        root = project.resolve()
        plan = None if replay_from else _plan(root, fresh)
        if not fresh and not replay_from:
            assert plan is not None
            typer.echo(json.dumps(estimate_plan(plan), indent=2))
            return
        _run(root, plan, replay_from)
    except (AcquirerEngineError, OSError, ValidationError) as error:
        typer.echo(f"Judge evaluation failed: {error}", err=True)
        raise typer.Exit(1) from error


def prepare_judges(
    analyst_run: Annotated[
        list[Path], typer.Option(help="Original run directory; repeat per source.")
    ],
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Freeze matched generation cases and write a shuffled blind reading packet.

    Args:
        analyst_run: Source directories containing snapshot.json and run.json.
        project: Repository receiving the corpus and human label template.
    Raises:
        typer.Exit: Sources are invalid or output already exists.
    """
    try:
        root = project.resolve()
        config = load_judge_config(root / "config/judges.yaml")
        corpus = prepare(
            analyst_run, config, root / "evals/cases/p5-calibration.json", root / "evals/labels"
        )
        typer.echo(f"Frozen cases: {len(corpus.cases)}; corpus: {corpus.digest}")
        typer.echo(f"Blind packet: {root / 'evals/labels/README.md'}")
    except (AcquirerEngineError, OSError, ValidationError) as error:
        typer.echo(f"Preparation failed: {error}", err=True)
        raise typer.Exit(1) from error
