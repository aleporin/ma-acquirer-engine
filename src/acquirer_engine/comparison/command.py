"""Compose an offline target comparison and an explicitly requested summary.

Owns: CLI arguments, shared resources, and immutable comparison artifacts.
Does not own: Buyer-page generation or changing feedback state.
"""

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Annotated
from uuid import uuid4

import typer
import yaml
from anthropic import AnthropicError
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from acquirer_engine import run_history
from acquirer_engine.bootstrap import build_services, model_resources
from acquirer_engine.comparison.ranking import compare_rankings
from acquirer_engine.comparison.results import ComparisonRun
from acquirer_engine.comparison.summary import ComparisonPolicy, summarize
from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, DataError
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.selection import Selection, prepare_selection
from acquirer_engine.settings import load_settings


def compare_targets(
    a: Path,
    b: Path,
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    summary: Annotated[bool, typer.Option(help="Include one optional narrative request.")] = False,
    replay: Annotated[
        bool, typer.Option("--replay/--fresh", help="Fresh permits paid summary.")
    ] = True,
) -> None:
    """Compare two target files; default output is entirely deterministic and free.

    Args:
        a, b: Target YAML files.
        project: Repository containing data, configuration, prompts, and feedback.
        summary: Enable one optional interpretation request.
        replay: False explicitly allows paid model access when summary is enabled.
    Raises:
        typer.Exit: Input error or optional summary failure; saved table remains usable.
    """
    try:
        if not replay and not summary:
            raise DataError("--fresh requires --summary; plain comparison is already offline")
        root, run_id = project.resolve(), uuid4().hex
        settings = load_settings(root / "config")
        sha, dirty = run_history.git_state(root)
        directory = root / "runs" / run_id
        with run_logger(
            root / "runs",
            run_id,
            sha,
            "comparison",
            sys.stderr,
            mode="replay" if replay else "live",
        ) as log:
            report = asyncio.run(
                _execute(root, directory, Deps(settings, log), a, b, sha, dirty, summary, replay)
            )
        _show(directory, report)
    except (AcquirerEngineError, OSError, ValidationError, yaml.YAMLError) as error:
        typer.echo(f"Comparison failed: {error}", err=True)
        raise typer.Exit(1) from error


async def _execute(
    root: Path,
    directory: Path,
    deps: Deps,
    a: Path,
    b: Path,
    sha: str,
    dirty: bool,
    summary: bool,
    replay: bool,
) -> ComparisonRun:
    started = perf_counter()
    left = prepare_selection(root, deps, target_file=a)
    right = prepare_selection(root, deps, target_file=b)
    if left.history != right.history or left.feedback != right.feedback:
        raise DataError("Inputs changed while comparing; retry with stable data and feedback")
    data = compare_rankings(
        left.packs[0].target,
        right.packs[0].target,
        [p.ranking for p in left.packs],
        [p.ranking for p in right.packs],
    )
    report = ComparisonRun(
        run_id=directory.name,
        git_sha=sha,
        source_dirty=dirty,
        mode=("replay" if replay else "live") if summary else "ranking-only",
        data=data,
        feedback=left.feedback,
        feedback_policy=left.feedback_policy,
    )
    if summary:
        report = await _with_summary(root, directory, deps, left, report, replay)
    report = report.model_copy(update={"latency_seconds": perf_counter() - started})
    _save(directory, report)
    return report


async def _with_summary(
    root: Path,
    directory: Path,
    deps: Deps,
    selected: Selection,
    report: ComparisonRun,
    replay: bool,
) -> ComparisonRun:
    policy = ComparisonPolicy.model_validate(
        yaml.safe_load((root / "config/comparison.yaml").read_text("utf-8"))
    )
    prompt = (root / "prompts" / policy.prompt_file).read_text("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    frozen = dict(
        settings=deps.settings.model_dump(mode="json"),
        prompt=prompt,
        policy=policy.model_dump(),
        inputs=report.model_dump(mode="json"),
    )
    with (directory / "comparison-input.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(frozen, indent=2) + "\n")
    async with model_resources(deps, replay=replay) as (model, _):
        runtime = build_services(
            deps,
            model,
            selected.history,
            directory,
            prompt,
            mode="replay" if replay else "live",
            cache_root=root / "cache",
        )
        updates: dict[str, object] = {"prompt_file": policy.prompt_file}
        try:
            result = await summarize(report.data, replace(deps, runtime=runtime), prompt, policy)
            updates["summary"] = result.summary
        except (
            AcquirerEngineError,
            UnexpectedModelBehavior,
            UsageLimitExceeded,
            ValidationError,
            AnthropicError,
        ) as error:
            updates["errors"] = (
                type(error).__name__ if isinstance(error, AnthropicError) else str(error),
            )
        updates.update(
            calls=tuple(runtime.model.ledger.entries),
            uncertain_cost_bound_usd=runtime.model.budget.uncertain,
        )
    return report.model_copy(update=updates)


def _save(directory: Path, report: ComparisonRun) -> None:
    environment = Environment(
        loader=PackageLoader("acquirer_engine.report", "templates"),
        autoescape=select_autoescape(("html",)),
        undefined=StrictUndefined,
    )
    html = environment.get_template("comparison.html").render(
        report=report, cost=sum(call.cost_usd for call in report.calls)
    )
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in (
        ("comparison.json", report.model_dump_json(indent=2) + "\n"),
        ("comparison.html", html),
    ):
        with (directory / name).open("x", encoding="utf-8") as stream:
            stream.write(text)


def _show(directory: Path, report: ComparisonRun) -> None:
    typer.echo(f"Comparison: {directory / 'comparison.html'}")
    typer.echo(f"Overlap: {len(report.data.overlap)} buyers ({report.data.overlap_fraction:.0%})")
    typer.echo("Acquirer | Rank A | Rank B | Delta (positive = higher for B)")
    for row in report.data.rows:
        delta = row.rank_delta if row.rank_delta is not None else "—"
        typer.echo(f"{row.acquirer} | {row.rank_a or '—'} | {row.rank_b or '—'} | {delta}")
    if report.errors:
        typer.echo("Summary failed: " + "; ".join(report.errors), err=True)
        raise typer.Exit(1)
