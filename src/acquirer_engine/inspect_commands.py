"""Inspect saved runs and compare scorecards without model access.

Owns: Read-only artifact CLI presentation and comparison exit status.
Does not own: Creating runs, invoking models, or modifying archives.
"""

from pathlib import Path
from typing import Annotated

import typer

from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.run_history import list_runs
from evals.diff import compare_scorecards
from evals.scorecard import read_scorecard


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
