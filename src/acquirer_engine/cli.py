"""Expose analysis and offline evaluation commands.

Owns: Argument parsing, dependency construction, and process exit status.
Does not own: Ranking, rationale generation, or provider retry policy.
"""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from anthropic import AnthropicError
from pydantic import ValidationError

from acquirer_engine.data.loader import load_transactions
from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, EvaluationError
from acquirer_engine.llm.archive import load_snapshot, run_directory
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.run_command import execute_replay, execute_run
from acquirer_engine.run_history import list_runs
from acquirer_engine.settings import load_settings
from evals.diff import compare_scorecards
from evals.graders.unit import grade as grade_unit
from evals.graders.unit import run_tests
from evals.harness import evaluate
from evals.phase1 import PreparedEvaluation, prepare_phase1
from evals.phase2 import prepare_phase2
from evals.phase3 import prepare_phase3
from evals.ranking.snapshot import verify_snapshot
from evals.scorecard import RunInfo, Scorecard, read_scorecard, write_scorecard


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


def _produce_scorecard(
    root: Path,
    deps: Deps,
    run: RunInfo,
    selection: list[int],
    results: Path,
    analyst_runs: list[Path] | None = None,
) -> tuple[Path, Scorecard]:
    prepared = PreparedEvaluation({}, {})
    if deps.settings.evaluation.phase in {"p1", "p2", "p3"}:
        rows = load_transactions(root / "data/ma_transactions_500.csv")
        deps.logger.info("csv_loaded", stage="eval", rows=len(rows))
        config = deps.settings.evaluation
        report = (
            run_tests(root, timeout=config.backtest.test_timeout_seconds)
            if 0 in selection
            else None
        )
        unit = grade_unit(next(layer for layer in config.layers if layer.id == 0), report)
        prepared = prepare_phase1(rows, deps, unit)
        verify_snapshot(root, prepared.artifacts["top10.json"])
    if deps.settings.evaluation.phase in {"p2", "p3"}:
        prepared = prepare_phase2(prepared, root, deps.settings.evidence.validation)
    if deps.settings.evaluation.phase == "p3":
        prepared = prepare_phase3(prepared, analyst_runs or [], deps.settings)
    card = evaluate(deps, run, selection, graders=prepared.graders)
    path = write_scorecard(card, results, artifacts=prepared.artifacts)
    deps.logger.info(
        "scorecard_written", stage="eval", path=str(path), source_dirty=run.source_dirty
    )
    return path, card


def run_evaluation(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    results: Annotated[Path | None, typer.Option(help="Alternative results directory.")] = None,
    replay: Annotated[bool, typer.Option("--replay/--fresh")] = True,
    ci: Annotated[bool, typer.Option(help="Select offline CI layers.")] = False,
    analyst_run: Annotated[
        list[Path] | None, typer.Option(help="Saved run.json; repeat for stability.")
    ] = None,
) -> None:
    """Write an offline scorecard and its measured phase artifacts.

    Args:
        project: Repository containing configuration and source history.
        results: Optional output root for repeated evaluations.
        replay: Must remain true while provider integration is unavailable.
        ci: Select layers zero through two.
        analyst_run: Optional stored analyst observations; never new provider calls.
    Raises:
        typer.Exit: The command is unavailable or evaluation fails.
    """
    if not replay:
        typer.echo("This phase supports offline replay evaluation only.", err=True)
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
            path, card = _produce_scorecard(
                root, deps, run, selection, results or root / "evals/results", analyst_run
            )
        typer.echo(f"Scorecard: {path}")
        for layer in card.layers:
            typer.echo(f"Layer {layer.id}: {layer.status}")
        if any(layer.status == "failed" for layer in card.layers):
            raise typer.Exit(1)
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


def run_product(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    replay: Annotated[bool, typer.Option("--replay/--fresh")] = True,
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
        sha, _ = _git_state(root)
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
                execute_run(root, directory, Deps(settings, log), sha, replay=replay)
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
    if verified != len(report.pages):
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
        sha, _ = _git_state(root)
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
                execute_replay(source, directory, snapshot, Deps(snapshot.settings, log), sha)
            )
        _show_run(directory, report)
    except (AcquirerEngineError, OSError) as error:
        typer.echo(f"Replay failed: {error}", err=True)
        raise typer.Exit(1) from error


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
                f"{run.latency_seconds:7.3f}  {run.git_sha[:8]}  {run.prompt_version}"
                + (f"  replay_of={run.replay_of}" if run.replay_of else "")
            )
    except (AcquirerEngineError, OSError) as error:
        typer.echo(f"History failed: {error}", err=True)
        raise typer.Exit(1) from error


def eval_judges() -> None:
    """Report that live evaluation is unavailable.

    Raises:
        typer.Exit: Live judging is not implemented.
    """
    typer.echo("Live judge evaluation is not implemented.", err=True)
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
    app.command("replay")(replay_product)
    app.command("runs")(show_runs)
    return app


def main() -> None:
    """Dispatch the installed command with machine-readable diagnostics."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    build_app()()


if __name__ == "__main__":
    main()
