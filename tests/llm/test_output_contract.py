"""Exercise the complete structured-output request through the SDK transport.

Owns: Strict output parameters and provider-compatible schema on the wire.
Does not own: Provider grammar execution or paid quality measurements.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from anthropic import transform_schema
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from acquirer_engine.deps import Deps
from acquirer_engine.llm.analyst import analyze_one, build_services
from acquirer_engine.llm.client import create_client
from tests.fixtures.rationale import evidence_context, rationale_payload


def provider_response(model: str, *, final: bool) -> httpx2.Response:
    args = (
        rationale_payload()
        if final
        else {
            "sector": "Services",
            "size_band": {"low": 100, "high": 400},
            "margin_band": None,
            "geography": None,
        }
    )
    if final:
        risks = args["risk_flags"]
        assert isinstance(risks, list)
        risks[0].pop("evidence_ids")
    return httpx2.Response(
        200,
        json={
            "id": "fixture-response",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [
                {
                    "type": "tool_use",
                    "id": "fixture-call",
                    "name": "final_result" if final else "get_comparable_deals",
                    "input": args,
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 100, "output_tokens": 30},
        },
    )


@pytest.mark.asyncio
async def test_provider_receives_strict_compatible_output_schema(
    deps: Deps, tmp_path: Path
) -> None:
    requests: list[dict[str, Any]] = []
    model_id = deps.settings.models.roles["analyst"].model_id

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return provider_response(model_id, final=len(requests) > 1)

    transport = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    context = evidence_context(deps.settings)
    async with create_client(
        deps.settings.analyst, http_client=transport, api_key="offline-test"
    ) as client:
        model = AnthropicModel(model_id, provider=AnthropicProvider(anthropic_client=client))
        runtime = build_services(
            deps,
            model,
            context.core.deals + context.comparable_deals,
            tmp_path,
            "Fixture instructions.",
            mode="test",
        )
        result = await analyze_one(context.core, replace(deps, runtime=runtime))
    assert result.status == "verified", result.errors
    assert result.claims_total == result.claims_verified == 4
    assert len(requests) == 2
    for request in requests:
        output = next(tool for tool in request["tools"] if tool["name"] == "final_result")
        assert output.get("strict") is True
        schema = output["input_schema"]
        assert transform_schema(schema) == schema
        assert next(iter(schema["properties"])) == "reasoning"
        assert request["max_tokens"] == deps.settings.analyst.max_output_tokens
        assert_risk_choices(schema)


def assert_risk_choices(schema: dict[str, Any]) -> None:
    """Inspect the emitted protocol's two mutually exclusive risk alternatives."""
    risks = schema["$defs"]["RiskFlag"]["anyOf"]
    choices = {risk["properties"]["basis"]["enum"][0]: risk for risk in risks}
    assert set(choices) == {"evidence", "judgment"}
    for risk in choices.values():
        assert risk["additionalProperties"] is False
        assert set(risk["required"]) == set(risk["properties"])
    evidence = choices["evidence"]["properties"]["evidence_ids"]
    assert evidence["type"] == "array" and evidence["minItems"] == 1
    assert "evidence_ids" not in choices["judgment"]["properties"]
