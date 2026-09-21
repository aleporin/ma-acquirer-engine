"""Reproduce incomplete drafts and inconsistent risk references offline.

Owns: Specific failed-page diagnostics and usage retained for rejected responses.
Does not own: Live model quality or automatic repair.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.llm.analyst import analyze_one, build_services
from tests.fixtures.rationale import evidence_context, rationale_payload


def draft_model(*, truncated: bool) -> FunctionModel:
    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returned = any(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        )
        if not returned:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_comparable_deals",
                        {
                            "sector": "Services",
                            "size_band": {"low": 100, "high": 400},
                            "margin_band": None,
                            "geography": None,
                        },
                    )
                ],
                usage=RequestUsage(input_tokens=100, output_tokens=30),
            )
        payload = rationale_payload()
        if not truncated:
            risks = payload["risk_flags"]
            assert isinstance(risks, list)
            risks[1]["basis"] = "judgment"
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, payload)],
            finish_reason="length" if truncated else "tool_call",
            usage=RequestUsage(input_tokens=100, output_tokens=30),
        )

    return FunctionModel(answer)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("truncated", "message"),
    [(True, "output token limit"), (False, "risk_flags.1: Value error, risk requires")],
)
async def test_rejected_draft_preserves_actionable_error_and_usage(
    deps: Deps, tmp_path: Path, truncated: bool, message: str
) -> None:
    context = evidence_context(deps.settings)
    runtime = build_services(
        deps,
        draft_model(truncated=truncated),
        context.core.deals + context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
    )
    result = await analyze_one(context.core, replace(deps, runtime=runtime))
    assert result.status == "failed"
    assert any(message in error for error in result.errors), result.errors
    assert result.rationale is None and result.claims_total == 0
    assert len(runtime.model.ledger.entries) == 2
    assert runtime.model.ledger.entries[-1].output_tokens == 30
    assert runtime.model.ledger.cost_usd == 0
    assert runtime.model.first_response.is_set()
