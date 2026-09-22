"""Exercise targeted repairs through real agent conversations.

Owns: Feedback, bounded attempts, first-pass provenance, and accounting.
Does not own: Live generation quality or tier escalation.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.factory import build_services
from acquirer_engine.stages.draft import draft_one
from tests.fixtures.rationale import evidence_context, rationale_payload


def enabled(deps: Deps) -> Deps:
    config = deps.settings.analyst.model_copy(update={"max_repairs": 1})
    return replace(deps, settings=deps.settings.model_copy(update={"analyst": config}))


def invalid_page(kind: str) -> dict[str, object]:
    raw = rationale_payload()
    if kind == "schema":
        raw["risk_flags"] = []
    elif kind == "prose":
        raw["reasoning"] = "The target has a 20% EBITDA margin."
    else:
        raw["precedent_activity"] = [
            {"transaction_id": "MA-2020-0010", "description": "A claimed own precedent."}
        ]
    return raw


def correcting_model(kind: str, feedback: list[str], *, correct: bool = True) -> FunctionModel:
    calls = 0

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            part = ToolCallPart(
                "get_comparable_deals",
                {"sector": "Services", "size_band": {"low": 100, "high": 400}},
            )
        else:
            if calls > 2:
                feedback.extend(
                    str(p.content)
                    for message in messages
                    for p in message.parts
                    if isinstance(p, RetryPromptPart)
                )
            raw = rationale_payload() if calls > 2 and correct else invalid_page(kind)
            part = ToolCallPart(info.output_tools[0].name, raw)
        return ModelResponse(parts=[part], usage=RequestUsage(input_tokens=100, output_tokens=30))

    return FunctionModel(respond)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,expected", [("schema", "risk_flags"), ("prose", "20%"), ("owner", "own-history")]
)
async def test_repair_corrects_rejected_output_and_preserves_first_pass(
    deps: Deps, tmp_path: Path, kind: str, expected: str
) -> None:
    deps = enabled(deps)
    context = evidence_context(deps.settings)
    feedback: list[str] = []
    runtime = build_services(
        deps,
        correcting_model(kind, feedback),
        context.core.deals + context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
    )
    page = await draft_one(context.core, deps.with_runtime(runtime))
    assert page.status == "verified", page.errors
    assert any(expected in text for text in feedback)
    attempts = page.model_dump()["attempts"]
    assert [a["stage"] for a in attempts] == ["analyst", "repair"]
    assert [a["status"] for a in attempts] == ["failed", "verified"]
    assert attempts[0]["claims_total"] == (0 if kind == "schema" else 4)
    assert attempts[1]["claims_verified"] == 4
    assert [c.stage for c in runtime.model.ledger.entries] == ["analyst", "analyst", "repair"]
    assert [c.attempt for c in runtime.model.ledger.entries] == [1, 2, 3]


@pytest.mark.asyncio
async def test_repair_stops_after_one_failed_correction(deps: Deps, tmp_path: Path) -> None:
    deps = enabled(deps)
    context = evidence_context(deps.settings)
    runtime = build_services(
        deps,
        correcting_model("schema", [], correct=False),
        context.core.deals + context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
    )
    page = await draft_one(context.core, deps.with_runtime(runtime))
    assert page.status == "failed"
    assert len(runtime.model.ledger.entries) == 3
    assert len(page.model_dump()["attempts"]) == 2
