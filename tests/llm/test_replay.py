"""Replay a whole agent conversation after independent resource construction.

Owns: Multi-request cache identity and repeated evidence validation.
Does not own: Paid generation or network access.
"""

import json
from functools import partial
from pathlib import Path

import httpx2
import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from acquirer_engine.deps import Deps
from acquirer_engine.factory import build_services
from acquirer_engine.llm.provider import create_client
from acquirer_engine.stages.draft import draft_one
from tests.fixtures.rationale import evidence_context, rationale_payload
from tests.llm.test_analyst import tool_model


@pytest.mark.asyncio
async def test_entire_agent_replays_with_no_provider(deps: Deps, tmp_path: Path) -> None:
    context = evidence_context(deps.settings)
    history = context.core.deals + context.comparable_deals
    cache = tmp_path / "cache"
    original = build_services(
        deps,
        tool_model(),
        history,
        tmp_path / "first",
        "Fixture instructions.",
        mode="test",
        cache_root=cache,
    )
    before = await draft_one(context.core, deps.with_runtime(original))
    replay = build_services(
        deps,
        None,
        history,
        tmp_path / "again",
        "Fixture instructions.",
        mode="replay",
        cache_root=cache,
    )
    after = await draft_one(context.core, deps.with_runtime(replay))
    assert after.status == "verified", after.errors
    assert after.rationale == before.rationale and after.tools == before.tools
    assert len(replay.model.ledger.entries) == 2
    assert replay.model.ledger.cost_usd == 0


def provider_response(calls: list[str], request: httpx2.Request) -> httpx2.Response:
    calls.append(str(request.url))
    body = json.loads(request.content)
    output = next(t["name"] for t in body["tools"] if t["name"] == "final_result")
    tool = "get_comparable_deals" if len(calls) == 1 else output
    args = (
        {"sector": "Services", "size_band": {"low": 100, "high": 400}}
        if len(calls) == 1
        else rationale_payload()
    )
    return httpx2.Response(
        200,
        json={
            "id": f"msg_{len(calls)}",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [
                {"type": "tool_use", "id": f"call_{len(calls)}", "name": tool, "input": args}
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 30,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 40,
            },
        },
    )


@pytest.mark.asyncio
async def test_provider_adapter_responses_replay_with_original_usage(
    deps: Deps, tmp_path: Path
) -> None:
    context = evidence_context(deps.settings)
    history = context.core.deals + context.comparable_deals
    calls: list[str] = []
    async with (
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(partial(provider_response, calls))
        ) as transport,
        create_client(
            deps.settings.analyst, http_client=transport, api_key="offline-test"
        ) as client,
    ):
        model = AnthropicModel(
            deps.settings.models.roles["analyst"].model_id,
            provider=AnthropicProvider(anthropic_client=client),
        )
        original = build_services(
            deps,
            model,
            history,
            tmp_path / "first",
            "Fixture instructions.",
            mode="test",
            cache_root=tmp_path / "cache",
        )
        before = await draft_one(context.core, deps.with_runtime(original))
    assert before.status == "verified", before.errors
    replay = build_services(
        deps,
        None,
        history,
        tmp_path / "again",
        "Fixture instructions.",
        mode="replay",
        cache_root=tmp_path / "cache",
    )
    after = await draft_one(context.core, deps.with_runtime(replay))
    assert after.status == "verified", after.errors
    assert after.rationale == before.rationale and len(calls) == 2
    usage = replay.model.ledger.entries[0]
    assert (usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens) == (160, 40, 20)
