"""Expose commands and inspect saved artifacts without creating provider clients.

Owns: Command registration, history display, scorecard differences, and process entry.
Does not own: Run composition, ranking, rendering, or evaluation mathematics.
"""

import os
from pathlib import Path
from typing import Annotated

import typer

from acquirer_engine.comparison.command import compare_targets
from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.feedback.command import flag_buyer
from acquirer_engine.run_command import replay_product, run_product
from acquirer_engine.run_history import list_runs
from evals.command import run_evaluation
from evals.diff import compare_scorecards
from evals.judges.command import eval_judges, prepare_judges
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
    app.command("flag")(flag_buyer)
    app.command("compare")(compare_targets)
    return app


def main() -> None:
    """Dispatch the installed command with machine-readable diagnostics."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    build_app()()


if __name__ == "__main__":
    main()
