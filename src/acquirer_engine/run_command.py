"""Expose analysis and offline evaluation commands.

Owns: Argument parsing, dependency construction, and process exit status.
Does not own: Ranking, rationale generation, or provider retry policy.
"""

import asyncio
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
from acquirer_engine.llm.archive import load_snapshot, run_directory
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.pipeline import execute_replay, execute_run
from acquirer_engine.report.render import render_report
from acquirer_engine.settings import load_settings
from acquirer_engine.target_input import TargetOverrides


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
