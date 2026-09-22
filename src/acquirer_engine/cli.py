"""Expose analysis and offline evaluation commands.

Owns: Argument parsing, dependency construction, and process exit status.
Does not own: Ranking, rationale generation, or provider retry policy.
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

from acquirer_engine import run_history
from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.inspect_commands import eval_diff, show_runs
from acquirer_engine.llm.archive import load_snapshot, run_directory
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.pipeline import execute_replay, execute_run
from acquirer_engine.settings import load_settings
from evals.command import run_evaluation
from evals.judges.command import eval_judges, prepare_judges


def run_product(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    replay: Annotated[bool, typer.Option("--replay/--fresh")] = True,
    no_tools: Annotated[bool, typer.Option(help="Disable evidence tools for ablation.")] = False,
    no_reviewer: Annotated[
        bool, typer.Option(help="Disable portfolio review for ablation.")
    ] = False,
) -> None:
    """Write structured rationale outcomes for the ranked assignment target.

    Args:
        project: Repository containing data, prompt, configuration, and cache.
        replay: Read cached responses only; fresh permits paid model calls.
    Raises:
        typer.Exit: Input preparation or one or more pages failed.
    """
    try:
        root = project.resolve()
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
        sha, dirty = run_history.git_state(root)
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
                    root, directory, Deps(settings, log), sha, replay=replay, source_dirty=dirty
                )
            )
        _show_run(directory, report)
    except (AcquirerEngineError, OSError, ValidationError, AnthropicError) as error:
        message = type(error).__name__ if isinstance(error, AnthropicError) else str(error)
        typer.echo(f"Run failed: {message}", err=True)
        raise typer.Exit(1) from error


def _show_run(directory: Path, report: AnalystRun) -> None:
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
        sha, dirty = run_history.git_state(root)
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


def build_app() -> typer.Typer:
    """Build an isolated CLI without module-level application state.

    Returns:
        Registered evaluation and placeholder commands.
    """
    app = typer.Typer(help="Dataset-grounded acquirer analysis.", add_completion=False)
    app.command("eval")(run_evaluation)
    app.command("eval-diff")(eval_diff)
    app.command("eval-judges")(eval_judges)
    app.command("prepare-judges")(prepare_judges)
    app.command("run")(run_product)
    app.command("replay")(replay_product)
    app.command("runs")(show_runs)
    return app


def main() -> None:
    """Dispatch the installed command with machine-readable diagnostics."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    build_app()()


if __name__ == "__main__":
    main()
