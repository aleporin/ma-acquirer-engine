"""Construct and close the resources shared by one execution.

Owns: Client lifetime and composition of agents, tools, ledger, cache, and trace.
Does not own: Run ordering, per-page routing, or evaluation policy.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from acquirer_engine.data.schema import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.llm.agents import build_analyst, build_reviewer
from acquirer_engine.llm.cache import ResponseCache
from acquirer_engine.llm.client import create_client
from acquirer_engine.llm.context import PageDeps, PageSession
from acquirer_engine.llm.cost import CostLedger, ExecutionMode
from acquirer_engine.llm.recording import RecordedModel
from acquirer_engine.llm.review_schema import PortfolioVerdicts
from acquirer_engine.llm.tools import EvidenceTools
from acquirer_engine.llm.trace import TraceWriter
from acquirer_engine.llm.trace_replay import ResponseArchive
from acquirer_engine.validation.schema import AcquirerRationale


@asynccontextmanager
async def model_resources(
    deps: Deps, *, replay: bool
) -> AsyncIterator[tuple[Model | None, Model | None]]:
    """Own the single provider connection outside the execution path.

    Args:
        deps: Loaded model identities and execution policy.
        replay: Offline mode creates no client.
    Yields:
        Primary and optional escalation model sharing one client.
    """
    if replay:
        yield None, None
        return
    async with create_client(deps.settings.analyst) as client:
        provider = AnthropicProvider(anthropic_client=client)
        model = AnthropicModel(deps.settings.models.roles["analyst"].model_id, provider=provider)
        escalation = (
            AnthropicModel(deps.settings.models.roles["escalation"].model_id, provider=provider)
            if deps.settings.analyst.escalation_enabled
            else None
        )
        yield model, escalation


@dataclass(frozen=True)
class AnalystServices:
    """Run-wide resources constructed once before any page tasks start."""

    agent: Agent[PageDeps, AcquirerRationale]
    model: RecordedModel
    tools: EvidenceTools
    trace: TraceWriter
    sparse_agent: Agent[PageDeps, AcquirerRationale] | None = None
    reviewer: Agent[tuple[str, ...], PortfolioVerdicts] | None = None
    sessions: dict[str, PageSession] = field(default_factory=dict)


def build_services(
    deps: Deps,
    model: Model | None,
    rows: tuple[Transaction, ...],
    root: Path,
    prompt: str,
    *,
    mode: ExecutionMode,
    cache_root: Path | None = None,
    archive: ResponseArchive | None = None,
    escalation_model: Model | None = None,
    auxiliary_prompts: dict[str, str] | None = None,
) -> AnalystServices:
    """Compose all agents and shared execution resources before fan-out.

    Args:
        deps: Loaded configuration and logger.
        model: Injected analyst model, or None for replay.
        rows: Eligible evidence history.
        root: Artifact directory.
        prompt: Primary instructions.
        mode: Live, replay, or test execution.
        cache_root: Shared response store.
        archive: Historical response source.
        escalation_model: Injected higher-tier model.
        auxiliary_prompts: Frozen sparse and reviewer instructions.
    Returns:
        Agents sharing one recording, cost, and evidence boundary.
    """
    trace = TraceWriter(root / "trace.jsonl")
    recorded = RecordedModel(
        model,
        deps,
        ResponseCache(cache_root or root / "cache"),
        CostLedger(deps.settings.models.roles["analyst"]),
        trace,
        mode=mode,
        archive=archive,
        escalation_model=escalation_model,
    )
    return _agents(recorded, deps, rows, prompt, auxiliary_prompts or {})


def _agents(
    recorded: RecordedModel,
    deps: Deps,
    rows: tuple[Transaction, ...],
    prompt: str,
    auxiliary: dict[str, str],
) -> AnalystServices:
    config = deps.settings.analyst
    sparse, review = auxiliary.get("sparse"), auxiliary.get("reviewer")
    reviewer = (
        build_reviewer(
            recorded, review, config.reviewer_max_output_tokens or config.max_output_tokens
        )
        if review
        else None
    )
    return AnalystServices(
        build_analyst(recorded, deps, prompt),
        recorded,
        EvidenceTools(rows, config),
        recorded.trace,
        build_analyst(recorded, deps, prompt + "\n" + sparse) if sparse else None,
        reviewer,
    )
