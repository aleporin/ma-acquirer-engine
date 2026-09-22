"""Expose the complete public command interface.

Owns: Commands, settings and logging setup, report display, and process exit status.
Does not own: Buyer selection, generation loops, provider transport, or eval mathematics.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from anthropic import AnthropicError
from pydantic import ValidationError

from acquirer_engine import replay as archives
from acquirer_engine.comparison.command import compare_targets
from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.feedback.command import flag_buyer
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.pipeline import execute_replay, execute_run
from acquirer_engine.replay import list_runs, load_snapshot, run_directory
from acquirer_engine.settings import load_settings
from acquirer_engine.stages.render import render_report
from acquirer_engine.stages.select import TargetOverrides
from evals.command import run_evaluation
from evals.diff import compare_scorecards
from evals.judges.command import eval_judges, prepare_judges
from evals.ranking.weight_command import experiment_weights, propose_weights
from evals.scorecard import read_scorecard


def run_product(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    replay: Annotated[bool, typer.Option("--replay/--fresh")] = True,
    no_tools: Annotated[bool, typer.Option(help="Disable evidence tools for ablation.")] = False,
    no_reviewer: Annotated[
        bool, typer.Option(help="Disable portfolio review for ablation.")
    ] = False,
    target: Annotated[Path | None, typer.Option(help="Partial target YAML file.")] = None,
    sector: Annotated[str | None, typer.Option()] = None,
    ev: Annotated[float | None, typer.Option(help="Enterprise value in USD millions.")] = None,
    margin: Annotated[float | None, typer.Option(help="EBITDA margin in percent.")] = None,
    geography: Annotated[str | None, typer.Option()] = None,
    ownership: Annotated[str | None, typer.Option()] = None,
    tag: Annotated[list[str] | None, typer.Option(help="Repeat to replace target tags.")] = None,
) -> None:
    """Rank buyers and write a report; replay never constructs a provider client.

    Args:
        project: Repository root.
        replay: False explicitly permits paid generation.
        target, sector, ev, margin, geography, ownership, tag: Target overrides.
        no_tools, no_reviewer: Explicit ablation options.
    Raises:
        typer.Exit: Invalid inputs or failed pages.
    """
    try:
        overrides = TargetOverrides(
            sector=sector,
            deal_size_mm=ev,
            ebitda_margin_pct=margin,
            geography=geography,
            ownership=ownership,
            tags=tuple(tag) if tag is not None else None,
        )
        _run_current(project.resolve(), replay, no_tools, no_reviewer, target, overrides)
    except (AcquirerEngineError, OSError, ValidationError, AnthropicError) as error:
        message = type(error).__name__ if isinstance(error, AnthropicError) else str(error)
        typer.echo(f"Run failed: {message}", err=True)
        raise typer.Exit(1) from error


def _run_current(
    root: Path,
    replay: bool,
    no_tools: bool,
    no_reviewer: bool,
    target_file: Path | None,
    overrides: TargetOverrides,
) -> None:
    settings = load_settings(root / "config")
    settings = settings.model_copy(
        update={
            "analyst": settings.analyst.model_copy(
                update={
                    "tools_enabled": settings.analyst.tools_enabled and not no_tools,
                    "reviewer_enabled": settings.analyst.reviewer_enabled and not no_reviewer,
                }
            )
        }
    )
    sha, dirty = archives.git_state(root)
    run_id = uuid4().hex
    directory = root / "runs" / run_id
    with run_logger(
        root / "runs",
        run_id,
        sha,
        settings.evaluation.prompt_version,
        sys.stderr,
        mode="replay" if replay else "live",
    ) as log:
        report = asyncio.run(
            execute_run(
                root,
                directory,
                Deps(settings, log),
                sha,
                replay=replay,
                source_dirty=dirty,
                target_file=target_file,
                overrides=overrides,
            )
        )
    _show_run(directory, report)


def _show_run(directory: Path, report: AnalystRun) -> None:
    snapshot = load_snapshot(directory)
    original = _source_report(directory, report)
    render_report(snapshot, report, directory, source_report=original)
    typer.echo(f"Report: {directory / 'index.html'}")
    typer.echo(f"Run: {directory / 'run.json'}")
    verified = sum(page.status == "verified" for page in report.pages)
    typer.echo(f"Verified pages: {verified}/{len(report.pages)}")
    if report.review and report.review.errors:
        typer.echo("Reviewer failed: " + "; ".join(report.review.errors), err=True)
    if verified != len(report.pages) or (report.review and report.review.errors):
        raise typer.Exit(1)


def replay_product(
    run_id: str,
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Replay a saved run through current validation, without provider access.

    Args:
        run_id: Full historical run ID shown by the runs command.
        project: Repository containing the selected archive.
    Raises:
        typer.Exit: The archive is unavailable or a replayed page fails.
    """
    try:
        root = project.resolve()
        source = run_directory(root, run_id)
        snapshot = load_snapshot(source)
        sha, dirty = archives.git_state(root)
        new_id = uuid4().hex
        directory = root / "runs" / new_id
        with run_logger(
            root / "runs",
            new_id,
            sha,
            snapshot.settings.evaluation.prompt_version,
            sys.stderr,
            mode="replay",
        ) as log:
            report = asyncio.run(
                execute_replay(
                    source,
                    directory,
                    snapshot,
                    Deps(snapshot.settings, log),
                    sha,
                    source_dirty=dirty,
                )
            )
        _show_run(directory, report)
    except (AcquirerEngineError, OSError) as error:
        typer.echo(f"Replay failed: {error}", err=True)
        raise typer.Exit(1) from error


def _source_report(directory: Path, report: AnalystRun) -> AnalystRun | None:
    if report.replay_of is None:
        return None
    root = directory.parent.parent
    for source in (root / "runs" / report.replay_of, root / "cache/replay" / report.replay_of):
        if (source / "run.json").is_file():
            snapshot = load_snapshot(source)
            return AnalystRun.model_validate_json(
                (source / "run.json").read_bytes(), context=snapshot.settings.evidence.validation
            )
    return None


def eval_diff(before: Path, after: Path) -> None:
    """Print scorecard changes and exit nonzero for regressions.

    Args:
        before: Earlier scorecard JSON path.
        after: Later scorecard JSON path.
    Raises:
        typer.Exit: A scorecard is invalid or a regression is found.
    """
    try:
        report = compare_scorecards(read_scorecard(before), read_scorecard(after))
    except AcquirerEngineError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    for line in report.lines:
        typer.echo(line)
    if report.regressions:
        typer.echo(f"Regressions: {len(report.regressions)}")
        raise typer.Exit(1)


def show_runs(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """List saved outcomes, sources, prompt versions, cost, and latency."""
    try:
        typer.echo(
            "RUN ID                            MODE    PAGES  USD       SECONDS  SOURCE    PROMPT"
        )
        for run in list_runs(project.resolve()):
            passed = sum(page.status == "verified" for page in run.pages)
            cost = sum(call.cost_usd for call in run.calls)
            typer.echo(
                f"{run.run_id}  {run.mode:6}  {passed}/{len(run.pages):<3}  {cost:.6f}  "
                f"{run.latency_seconds:7.3f}  {run.git_sha[:8]}{'*' if run.source_dirty else ''}  "
                f"{run.prompt_version}" + (f"  replay_of={run.replay_of}" if run.replay_of else "")
            )
    except (AcquirerEngineError, OSError) as error:
        typer.echo(f"History failed: {error}", err=True)
        raise typer.Exit(1) from error


def build_app() -> typer.Typer:
    """Build an isolated CLI without module-level application state.

    Returns:
        Registered product and evaluation commands.
    """
    app = typer.Typer(help="Dataset-grounded acquirer analysis.", add_completion=False)
    app.command("eval")(run_evaluation)
    app.command("eval-diff")(eval_diff)
    app.command("eval-judges")(eval_judges)
    app.command("prepare-judges")(prepare_judges)
    app.command("run")(run_product)
    app.command("replay")(replay_product)
    app.command("runs")(show_runs)
    app.command("flag")(flag_buyer)
    app.command("compare")(compare_targets)
    app.command("propose-weights")(propose_weights)
    app.command("experiment-weights")(experiment_weights)
    return app


def main() -> None:
    """Dispatch the installed command with machine-readable diagnostics."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    build_app()()


if __name__ == "__main__":
    main()
