"""Compose one product run at the command boundary.

Owns: Input preparation, provider lifecycle, and the structured run artifact.
Does not own: Report rendering, evaluation, or per-page repair.
"""

from dataclasses import replace
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
from acquirer_engine.llm.analyst import build_services
from acquirer_engine.llm.client import create_client
from acquirer_engine.llm.cost import ExecutionMode
from acquirer_engine.llm.pipeline import run_analysts
from acquirer_engine.llm.results import AnalystRun
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
    if replay:
        result = await _execute(None, "replay", root, directory, deps, sha, history, packs, prompt)
    else:
        async with create_client(deps.settings.analyst) as client:
            model = AnthropicModel(
                deps.settings.models.roles["analyst"].model_id,
                provider=AnthropicProvider(anthropic_client=client),
            )
            result = await _execute(
                model, "live", root, directory, deps, sha, history, packs, prompt
            )
    (directory / "run.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


async def _execute(
    model: Model | None,
    mode: ExecutionMode,
    root: Path,
    directory: Path,
    deps: Deps,
    sha: str,
    history: tuple[Transaction, ...],
    packs: list[CorePack],
    prompt: str,
) -> AnalystRun:
    started = perf_counter()
    services = build_services(
        deps, model, history, directory, prompt, mode=mode, cache_root=root / "cache"
    )
    pages = await run_analysts(packs, replace(deps, runtime=services))
    return AnalystRun.model_validate(
        dict(
            mode=mode,
            git_sha=sha,
            prompt_version=deps.settings.evaluation.prompt_version,
            latency_seconds=perf_counter() - started,
            pages=pages,
            calls=services.model.ledger.entries,
        ),
        context=deps.settings.evidence.validation,
    )
