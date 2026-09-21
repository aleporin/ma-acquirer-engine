"""Compose one product run at the command boundary.

Owns: Input preparation, provider lifecycle, and the structured run artifact.
Does not own: Report rendering, evaluation, or per-page repair.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from acquirer_engine.data.loader import load_transactions
from acquirer_engine.data.schema import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.evidence.pack import CorePack, build_core_pack
from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.llm.analyst import AnalystServices, build_services
from acquirer_engine.llm.archive import RunSnapshot, save_snapshot
from acquirer_engine.llm.client import create_client
from acquirer_engine.llm.cost import ExecutionMode
from acquirer_engine.llm.pipeline import run_analysts
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.llm.trace_replay import ResponseArchive
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.ranking.target import assignment_target


def prepare_inputs(root: Path, deps: Deps) -> tuple[tuple[Transaction, ...], list[CorePack]]:
    """Load eligible history and build the assignment target's ranked core packs.

    Args:
        root: Repository containing the input CSV.
        deps: Run settings and logger.
    Returns:
        Eligible tool history and ordered candidate packs.
    """
    rows = load_transactions(root / "data/ma_transactions_500.csv")
    config = deps.settings.scoring
    fitted = fit_features(rows, config, reference_year=config.reference_year)
    history = tuple(row for buyer in fitted.acquirers.values() for row in buyer.rows)
    target = assignment_target(history, config)
    ranked = rank_acquirers(fitted, target, config)[: config.top_k]
    packs = [
        build_core_pack(fitted.acquirers[item.acquirer], item, target, deps.settings.evidence.pack)
        for item in ranked
    ]
    deps.logger.info("ranking_computed", stage="ranking", rows=len(rows), candidates=len(packs))
    return history, packs


async def execute_run(
    root: Path, directory: Path, deps: Deps, sha: str, *, replay: bool
) -> AnalystRun:
    """Execute replay without a client, or own one client for an explicitly fresh run.

    Args:
        root: Repository with configuration, prompt, data, and response cache.
        directory: Artifact directory for this execution.
        deps: Settings and run-scoped logger constructed by the CLI.
        sha: Source revision recorded in the output.
        replay: False permits paid provider access; true never constructs a client.
    Returns:
        Persisted run with all page outcomes and observed usage.
    """
    history, packs = prepare_inputs(root, deps)
    prompt = (root / "prompts" / deps.settings.analyst.prompt_file).read_text(encoding="utf-8")
    snapshot = RunSnapshot(
        run_id=directory.name,
        git_sha=sha,
        settings=deps.settings,
        prompt=prompt,
        history=history,
        packs=tuple(packs),
    )
    if replay:
        return await execute_prepared(
            snapshot, directory, deps, mode="replay", cache_root=root / "cache"
        )
    async with create_client(deps.settings.analyst) as client:
        model = AnthropicModel(
            deps.settings.models.roles["analyst"].model_id,
            provider=AnthropicProvider(anthropic_client=client),
        )
        return await execute_prepared(
            snapshot, directory, deps, model=model, mode="live", cache_root=root / "cache"
        )


async def execute_prepared(
    snapshot: RunSnapshot,
    directory: Path,
    deps: Deps,
    *,
    mode: ExecutionMode,
    model: Model | None = None,
    cache_root: Path | None = None,
    archive: ResponseArchive | None = None,
    replay_of: RunSnapshot | None = None,
) -> AnalystRun:
    """Persist frozen inputs, then execute with injected model or archived responses.

    Args:
        snapshot: Actual input values used for this execution.
        directory: New output directory, independent of any source archive.
        deps: Logger and shared resources; settings are bound to the snapshot.
        mode: Live, test, or strictly offline replay.
        model: One injected provider or offline test model.
        cache_root: Optional shared request cache.
        archive: Original exchanges for replay by run ID.
        replay_of: Source identity, distinct from this execution's revision.
    Returns:
        Persisted outcomes and usage; rejected responses remain in the trace.
    """
    save_snapshot(directory, snapshot)
    deps = replace(deps, settings=snapshot.settings)
    started = perf_counter()
    services = build_services(
        deps,
        model,
        snapshot.history,
        directory,
        snapshot.prompt,
        mode=mode,
        cache_root=cache_root,
        archive=archive,
    )
    pages = await run_analysts(list(snapshot.packs), replace(deps, runtime=services))
    result = _run_result(snapshot, mode, services, pages, perf_counter() - started, replay_of)
    (directory / "run.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def _run_result(
    snapshot: RunSnapshot,
    mode: ExecutionMode,
    services: AnalystServices,
    pages: list[PageResult],
    duration: float,
    replay_of: RunSnapshot | None,
) -> AnalystRun:
    return AnalystRun.model_validate(
        dict(
            run_id=snapshot.run_id,
            mode=mode,
            git_sha=snapshot.git_sha,
            replay_of=replay_of.run_id if replay_of else None,
            source_git_sha=replay_of.git_sha if replay_of else None,
            prompt_version=snapshot.settings.evaluation.prompt_version,
            latency_seconds=duration,
            pages=pages,
            calls=services.model.ledger.entries,
        ),
        context=snapshot.settings.evidence.validation,
    )


async def execute_replay(
    source: Path, directory: Path, snapshot: RunSnapshot, deps: Deps, sha: str
) -> AnalystRun:
    """Replay original inputs and responses through the current tools and verifier.

    Args:
        source: Original archive directory, always read-only.
        directory: New run's output directory.
        snapshot: Original configuration, prompt, history, and core evidence.
        deps: Logger for this execution; no provider client is constructed.
        sha: Current executing source revision, not the original source revision.
    Returns:
        New replay outcomes with explicit source lineage and zero new model spend.
    """
    archive = ResponseArchive.from_trace(source / "trace.jsonl")
    current = snapshot.model_copy(
        update={"run_id": directory.name, "git_sha": sha, "created_at": datetime.now(UTC)}
    )
    return await execute_prepared(
        current, directory, deps, mode="replay", archive=archive, replay_of=snapshot
    )
