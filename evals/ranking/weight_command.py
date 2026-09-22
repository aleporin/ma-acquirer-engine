"""Expose recorded proposals and offline weight experiments as separate commands.

Owns: Resource assembly, immutable input snapshots, and result artifacts.
Does not own: Promoting experiment winners into the product ranking policy.
"""

import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from anthropic import AnthropicError
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from acquirer_engine.data import Transaction, load_transactions
from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, EvaluationError
from acquirer_engine.factory import build_services, model_resources
from acquirer_engine.llm.trace import ResponseArchive
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.replay import git_state
from acquirer_engine.settings import Settings, load_settings
from evals.ranking.experiment import ExperimentReport, run_experiment
from evals.ranking.packet import build_packet, packet_digest
from evals.ranking.proposals import (
    ProposalRun,
    ProposalSnapshot,
    proposal_settings,
    request_proposals,
)
from evals.ranking.weighting import ExperimentPolicy, load_policy, validate_proposals


def digest(text: str) -> str:
    """Fingerprint the exact saved input text or proposal artifact."""
    return hashlib.sha256(text.encode()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def _load(directory: Path) -> tuple[ProposalSnapshot, ProposalRun]:
    encoded = (directory / "input.json").read_text("utf-8")
    snapshot = ProposalSnapshot.model_validate_json(encoded)
    run = ProposalRun.model_validate_json((directory / "proposal.json").read_bytes())
    if (
        run.snapshot_sha256 != digest(encoded)
        or snapshot.packet_sha256 != packet_digest(snapshot.packet)
        or run.packet_sha256 != snapshot.packet_sha256
    ):
        raise EvaluationError("Proposal input digest mismatch")
    if run.run_id != directory.name or run.git_sha != snapshot.git_sha:
        raise EvaluationError("Proposal source identity mismatch")
    if run.errors:
        raise EvaluationError("The proposal run failed; no hypotheses are eligible")
    validate_proposals(run.candidates, snapshot.policy, snapshot.settings.scoring)
    return snapshot, run


def checked_proposal(
    directory: Path,
    rows: Sequence[Transaction],
    settings: Settings,
    policy: ExperimentPolicy,
) -> tuple[ProposalSnapshot, ProposalRun]:
    """Reject changed data or policy before selecting any candidate."""
    snapshot, run = _load(directory)
    if snapshot.policy != policy or snapshot.settings.scoring != settings.scoring:
        raise EvaluationError("Proposal configuration differs from the frozen experiment")
    if snapshot.packet_sha256 != packet_digest(build_packet(rows, policy, settings.scoring)):
        raise EvaluationError("Proposal history differs from the current dataset")
    return snapshot, run


def _fresh_snapshot(root: Path) -> ProposalSnapshot:
    settings = load_settings(root / "config")
    policy = load_policy(root / "config/ranking_experiment.yaml")
    packet = build_packet(
        load_transactions(root / "data/ma_transactions_500.csv"), policy, settings.scoring
    )
    sha, dirty = git_state(root)
    return ProposalSnapshot(
        settings=proposal_settings(settings, policy),
        policy=policy,
        packet=packet,
        packet_sha256=packet_digest(packet),
        prompt=(root / "prompts" / policy.prompt_file).read_text("utf-8"),
        git_sha=sha,
        source_dirty=dirty,
    )


async def _request(
    snapshot: ProposalSnapshot,
    directory: Path,
    deps: Deps,
    source: Path | None,
) -> ProposalRun:
    encoded = snapshot.model_dump_json(indent=2) + "\n"
    _write(directory / "input.json", encoded)
    report = ProposalRun(
        run_id=directory.name,
        replay_of=source.name if source else None,
        git_sha=snapshot.git_sha,
        source_dirty=snapshot.source_dirty,
        packet_sha256=snapshot.packet_sha256,
        snapshot_sha256=digest(encoded),
    )
    async with model_resources(deps, replay=source is not None) as (model, _):
        services = build_services(
            deps,
            model,
            (),
            directory,
            snapshot.prompt,
            mode="replay" if source else "live",
            archive=ResponseArchive.from_trace(source / "trace.jsonl") if source else None,
        )
        try:
            proposed = await request_proposals(
                snapshot.packet, deps.with_runtime(services), snapshot.prompt, snapshot.policy
            )
            report = report.model_copy(update={"candidates": proposed.candidates})
        except (
            AcquirerEngineError,
            UnexpectedModelBehavior,
            UsageLimitExceeded,
            ValidationError,
            AnthropicError,
        ) as error:
            report = report.model_copy(update={"errors": (type(error).__name__,)})
        report = report.model_copy(
            update={
                "calls": tuple(services.model.ledger.entries),
                "uncertain_cost_bound_usd": services.model.budget.uncertain,
            }
        )
    _write(directory / "proposal.json", report.model_dump_json(indent=2) + "\n")
    return report


def propose_weights(
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
    source: Annotated[
        Path | None, typer.Option(help="Saved proposal directory for replay.")
    ] = None,
    fresh: Annotated[
        bool, typer.Option(help="Explicitly permit one paid proposal request.")
    ] = False,
) -> None:
    """Record at most one proposal request; the default requires an offline source."""
    try:
        if fresh and source is not None:
            raise EvaluationError("--fresh cannot use --source")
        if not fresh and source is None:
            raise EvaluationError("Replay requires --source; --fresh permits one paid request")
        root = project.resolve()
        snapshot = _load(source)[0] if source is not None else _fresh_snapshot(root)
        directory = root / "runs/weight-proposals" / uuid4().hex
        with run_logger(
            directory.parent,
            directory.name,
            snapshot.git_sha,
            snapshot.policy.prompt_file,
            sys.stderr,
            mode="live" if fresh else "replay",
        ) as log:
            report = asyncio.run(
                _request(snapshot, directory, Deps(snapshot.settings, log), source)
            )
        typer.echo(f"Proposal: {directory / 'proposal.json'}")
        cost = sum(call.cost_usd for call in report.calls)
        typer.echo(f"Candidates: {len(report.candidates)}; cost: ${cost:.6f}")
        if report.errors:
            raise EvaluationError("Proposal failed: " + ", ".join(report.errors))
    except (AcquirerEngineError, OSError, ValidationError, AnthropicError) as error:
        message = type(error).__name__ if isinstance(error, AnthropicError) else str(error)
        typer.echo(f"Weight proposal failed: {message}", err=True)
        raise typer.Exit(1) from error


def summary(report: ExperimentReport) -> str:
    """Render measured results without claiming an independent untouched test."""
    lines = [
        "# Exploratory ranking weights",
        "",
        "The 2022–2024 benchmark was already inspected during development. These results",
        "are exploratory, not proof of generalization. Production weights are unchanged.",
        "",
        f"Frozen selection: `{report.selection.selected}`; "
        f"objective: pooled recall@{report.top_k}, then MRR.",
        f"Type-only winner: `{report.selection.type_winner}`; "
        f"buyer-adjusted: `{report.selection.buyer_winner}`.",
        f"Benchmark: {report.benchmark.test_rows} queries, "
        f"{report.benchmark.unseen_labels} queries with unseen buyer labels.",
        "",
        f"| Method | Recall@{report.top_k} | MRR | nDCG@{report.top_k} |",
        "|---|---:|---:|---:|",
    ]
    for name, values in report.benchmark.metrics.items():
        lines.append(
            f"| {name} | {values['recall_at_k']:.2%} | "
            f"{values['mrr']:.4f} | {values['ndcg_at_k']:.4f} |"
        )
    lines += [
        "",
        f"Selected minus baseline, paired {report.policy.confidence:.0%} "
        f"bootstrap interval for recall@{report.top_k}:",
        "",
    ]
    for name, metrics in report.lift.items():
        value = metrics["recall_at_k"]
        lines.append(
            f"- {name}: {value.mean * 100:+.2f} percentage points "
            f"[{value.low * 100:+.2f}, {value.high * 100:+.2f}]"
        )
    lines += [
        "",
        "Intervals resample transactions and do not adjust for repeated buyers or",
        "development/search decisions. Observed purchases do not establish mandates.",
        "",
    ]
    return "\n".join(lines)


def experiment_weights(
    proposal: Path,
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Evaluate frozen proposals offline; never request or replace model output."""
    try:
        root = project.resolve()
        settings = load_settings(root / "config")
        policy = load_policy(root / "config/ranking_experiment.yaml")
        rows = load_transactions(root / "data/ma_transactions_500.csv")
        snapshot, run = checked_proposal(proposal, rows, settings, policy)
        report = run_experiment(rows, run.candidates, settings.scoring, policy)
        directory = root / "runs/weight-experiments" / uuid4().hex
        sha, dirty = git_state(root)
        provenance = dict(
            git_sha=sha,
            source_dirty=dirty,
            proposal_run_id=run.run_id,
            proposal_sha256=digest((proposal / "proposal.json").read_text("utf-8")),
            packet_sha256=snapshot.packet_sha256,
        )
        _write(directory / "provenance.json", json.dumps(provenance, indent=2) + "\n")
        _write(directory / "experiment.json", report.model_dump_json(indent=2) + "\n")
        _write(directory / "summary.md", summary(report))
        typer.echo(summary(report))
        typer.echo(f"Results: {directory}")
    except (AcquirerEngineError, OSError, ValidationError) as error:
        typer.echo(f"Weight experiment failed: {error}", err=True)
        raise typer.Exit(1) from error
