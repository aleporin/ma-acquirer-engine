"""Expose offline evaluation commands.

Owns: Argument parsing, dependency construction, and process exit status.
Does not own: Ranking, rationale generation, or live provider access.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from pydantic import ValidationError

from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, EvaluationError
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.settings import load_settings
from evals.diff import compare_scorecards
from evals.harness import evaluate
from evals.scorecard import RunInfo, read_scorecard, write_scorecard


def _git_state(root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise EvaluationError("Evaluation requires a repository with a base commit") from error
    return revision, bool(changes.strip())


def run_evaluation(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    results: Annotated[Path | None, typer.Option(help="Alternative results directory.")] = None,
    replay: Annotated[bool, typer.Option("--replay/--fresh")] = True,
    ci: Annotated[bool, typer.Option(help="Select offline CI layers.")] = False,
) -> None:
    """Write a Phase 0 scorecard using only offline stub graders.

    Args:
        project: Repository containing configuration and source history.
        results: Optional output root for repeated evaluations.
        replay: Must remain true during Phase 0.
        ci: Select layers zero through two.
    Raises:
        typer.Exit: The command is unavailable or evaluation fails.
    """
    if not replay:
        typer.echo("Phase 0 supports offline replay evaluation only.", err=True)
        raise typer.Exit(2)
    try:
        root = project.resolve()
        settings = load_settings(root / "config")
        sha, dirty = _git_state(root)
        run = RunInfo(
            git_sha=sha, source_dirty=dirty, run_id=uuid4().hex, created_at=datetime.now(UTC)
        )
        with run_logger(
            root / "runs", run.run_id, sha, settings.evaluation.prompt_version, sys.stderr
        ) as log:
            deps = Deps(settings=settings, logger=log)
            selection = settings.evaluation.ci_layers if ci else settings.evaluation.offline_layers
            card = evaluate(deps, run, selection)
            path = write_scorecard(card, results or root / "evals/results")
            log.info("scorecard_written", stage="eval", path=str(path), source_dirty=dirty)
        typer.echo(f"Scorecard: {path}")
        for layer in card.layers:
            typer.echo(f"Layer {layer.id}: {layer.status}")
    except (AcquirerEngineError, OSError, ValidationError) as error:
        typer.echo(f"Evaluation failed: {error}", err=True)
        raise typer.Exit(1) from error


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


def run_product(replay: Annotated[bool, typer.Option("--replay/--fresh")] = True) -> None:
    """Report that product execution is unavailable in this phase.

    Args:
        replay: Requested mode; neither mode is implemented yet.
    Raises:
        typer.Exit: Phase 0 contains no product pipeline.
    """
    typer.echo("Phase 0: ranking and rationale generation are not implemented.", err=True)
    raise typer.Exit(2)


def eval_judges() -> None:
    """Report that live evaluation is unavailable.

    Raises:
        typer.Exit: Phase 0 contains no live judge implementation.
    """
    typer.echo("Phase 0: live judge evaluation is not implemented.", err=True)
    raise typer.Exit(2)


def build_app() -> typer.Typer:
    """Build an isolated CLI without module-level application state.

    Returns:
        Registered evaluation and placeholder commands.
    """
    app = typer.Typer(help="Dataset-grounded acquirer analysis.", add_completion=False)
    app.command("eval")(run_evaluation)
    app.command("eval-diff")(eval_diff)
    app.command("eval-judges")(eval_judges)
    app.command("run")(run_product)
    return app


def main() -> None:
    """Dispatch the installed command."""
    build_app()()


if __name__ == "__main__":
    main()
