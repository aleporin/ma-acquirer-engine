"""Compose one product run at the command boundary.

Owns: Input preparation, provider lifecycle, and the structured run artifact.
Does not own: Report rendering, evaluation, or per-page repair.
"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic_ai.models import Model

from acquirer_engine.bootstrap import AnalystServices, build_services, model_resources
from acquirer_engine.data.schema import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.archive import RunSnapshot, save_snapshot
from acquirer_engine.llm.batch import run_analysts
from acquirer_engine.llm.cost import ExecutionMode
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.llm.review_schema import ReviewResult
from acquirer_engine.llm.reviewer import review_portfolio
from acquirer_engine.llm.trace_replay import ResponseArchive
from acquirer_engine.selection import prepare_selection
from acquirer_engine.target_input import TargetOverrides


def prepare_inputs(root: Path, deps: Deps) -> tuple[tuple[Transaction, ...], list[CorePack]]:
    """Load eligible history and build the assignment target's ranked core packs.

    Args:
        root: Repository containing the input CSV.
        deps: Run settings and logger.
    Returns:
        Eligible tool history and ordered candidate packs.
    """
    selected = prepare_selection(root, deps)
    return selected.history, list(selected.packs)


async def execute_run(
    root: Path,
    directory: Path,
    deps: Deps,
    sha: str,
    *,
    replay: bool,
    source_dirty: bool = False,
    target_file: Path | None = None,
    overrides: TargetOverrides | None = None,
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
    selected = prepare_selection(root, deps, target_file=target_file, overrides=overrides)
    prompt = (root / "prompts" / deps.settings.analyst.prompt_file).read_text(encoding="utf-8")
    snapshot = RunSnapshot(
        run_id=directory.name,
        git_sha=sha,
        settings=deps.settings,
        source_dirty=source_dirty,
        prompt=prompt,
        auxiliary_prompts=_load_prompts(root, deps),
        history=selected.history,
        packs=selected.packs,
        feedback=selected.feedback,
        feedback_policy=selected.feedback_policy,
    )
    async with model_resources(deps, replay=replay) as (model, escalation):
        return await execute_prepared(
            snapshot,
            directory,
            deps,
            model=model,
            mode="replay" if replay else "live",
            escalation_model=escalation,
            cache_root=root / "cache",
        )


def _load_prompts(root: Path, deps: Deps) -> dict[str, str]:
    config = deps.settings.analyst
    files = {
        "sparse": config.sparse_prompt_file,
        "reviewer": config.reviewer_prompt_file if config.reviewer_enabled else None,
    }
    return {
        role: (root / "prompts" / name).read_text(encoding="utf-8")
        for role, name in files.items()
        if name
    }


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
    escalation_model: Model | None = None,
) -> AnalystRun:
    """Persist frozen inputs, then execute with injected model or archived responses.

    Args:
        snapshot: Frozen inputs.
        directory: New artifact directory.
        deps: Logger and run resources.
        mode: Live, test, or strictly offline replay.
        model: One injected provider or offline test model.
        cache_root, archive: Response sources.
        replay_of: Historical lineage.
        escalation_model: Injected higher-tier model.
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
        escalation_model=escalation_model,
        auxiliary_prompts=snapshot.auxiliary_prompts,
    )
    pages = await run_analysts(list(snapshot.packs), replace(deps, runtime=services))
    final, review = await review_portfolio(pages, replace(deps, runtime=services))
    result = _run_result(snapshot, mode, services, final, perf_counter() - started, replay_of)
    return _save_report(directory, result, pages, review, services.model.budget.uncertain)


def _save_report(
    directory: Path,
    result: AnalystRun,
    original: list[PageResult],
    review: ReviewResult | None,
    uncertain_cost: float,
) -> AnalystRun:
    result = result.model_copy(
        update={
            "before_review": original if review else [],
            "review": review,
            "uncertain_cost_bound_usd": uncertain_cost,
        }
    )
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
            tools_enabled=snapshot.settings.analyst.tools_enabled,
            reviewer_enabled=snapshot.settings.analyst.reviewer_enabled,
            git_sha=snapshot.git_sha,
            source_dirty=snapshot.source_dirty,
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
    source: Path,
    directory: Path,
    snapshot: RunSnapshot,
    deps: Deps,
    sha: str,
    *,
    source_dirty: bool = False,
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
    archive = ResponseArchive.from_trace(source / "trace.jsonl", report_path=source / "run.json")
    current = snapshot.model_copy(
        update={
            "run_id": directory.name,
            "git_sha": sha,
            "source_dirty": source_dirty,
            "created_at": datetime.now(UTC),
        }
    )
    return await execute_prepared(
        current, directory, deps, mode="replay", archive=archive, replay_of=snapshot
    )
