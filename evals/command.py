"""Assemble measured evaluation layers and expose the offline eval commands.

Owns: Eval configuration, observation loading, scorecard writing, and exit status.
Does not own: Product execution, ranking mathematics, or paid judge calls.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from pydantic import ValidationError

from acquirer_engine import run_history
from acquirer_engine.data.loader import load_transactions
from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.settings import load_settings
from evals.graders.unit import grade as grade_unit
from evals.graders.unit import run_tests
from evals.harness import evaluate
from evals.phase1 import PreparedEvaluation, prepare_phase1
from evals.phase2 import prepare_phase2
from evals.phase3 import prepare_phase3
from evals.phase4 import prepare_phase4
from evals.phase5 import prepare_phase5
from evals.ranking.snapshot import verify_snapshot
from evals.scorecard import RunInfo, Scorecard, write_scorecard


def _produce_scorecard(
    root: Path,
    deps: Deps,
    run: RunInfo,
    selection: list[int],
    results: Path,
    analyst_runs: list[Path] | None = None,
    judge_run: Path | None = None,
) -> tuple[Path, Scorecard]:
    prepared = PreparedEvaluation({}, {})
    if deps.settings.evaluation.phase in {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}:
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
    if deps.settings.evaluation.phase in {"p2", "p3", "p4", "p5", "p6", "p7"}:
        prepared = prepare_phase2(prepared, root, deps.settings.evidence.validation)
    if deps.settings.evaluation.phase == "p3":
        prepared = prepare_phase3(prepared, analyst_runs or [], deps.settings)
    if deps.settings.evaluation.phase in {"p4", "p5", "p6", "p7"}:
        prepared = prepare_phase4(prepared, analyst_runs or [], deps.settings)
    if judge_run is not None and deps.settings.evaluation.phase in {"p5", "p6", "p7"}:
        prepared = prepare_phase5(prepared, judge_run)
    card = evaluate(deps, run, selection, graders=prepared.graders)
    path = write_scorecard(card, results, artifacts=prepared.artifacts)
    deps.logger.info(
        "scorecard_written", stage="eval", path=str(path), source_dirty=run.source_dirty
    )
    return path, card


def _execute_evaluation(
    root: Path,
    results: Path | None,
    analyst_run: list[Path] | None,
    judge_run: Path | None,
    ci: bool,
) -> tuple[Path, Scorecard]:
    settings = load_settings(root / "config")
    sha, dirty = run_history.git_state(root)
    run = RunInfo(git_sha=sha, source_dirty=dirty, run_id=uuid4().hex, created_at=datetime.now(UTC))
    with run_logger(
        root / "runs", run.run_id, sha, settings.evaluation.prompt_version, sys.stderr
    ) as log:
        deps = Deps(settings=settings, logger=log)
        selection = settings.evaluation.ci_layers if ci else settings.evaluation.offline_layers
        path, card = _produce_scorecard(
            root,
            deps,
            run,
            selection,
            results or root / "evals/results",
            analyst_run,
            judge_run,
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
    judge_run: Annotated[
        Path | None, typer.Option(help="Saved judge directory; no provider calls.")
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
        path, card = _execute_evaluation(root, results, analyst_run, judge_run, ci)
        typer.echo(f"Scorecard: {path}")
        for layer in card.layers:
            typer.echo(f"Layer {layer.id}: {layer.status}")
        if any(layer.status == "failed" for layer in card.layers):
            raise typer.Exit(1)
    except (AcquirerEngineError, OSError, ValidationError) as error:
        typer.echo(f"Evaluation failed: {error}", err=True)
        raise typer.Exit(1) from error
