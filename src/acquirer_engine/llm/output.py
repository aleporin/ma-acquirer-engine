"""Prepare structured output and retain specific rejection reasons.

Owns: Provider-compatible output schemas, truncation checks, and schema diagnostics.
Does not own: Repair, evidence validation, client construction, or usage accounting.
"""

from dataclasses import replace
from typing import Any

from anthropic import transform_schema
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestParameters

from acquirer_engine.errors import AcquirerEngineError, LLMInvalidOutput


def _output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    schema = transform_schema(schema)
    risk = schema.get("$defs", {}).get("RiskFlag")
    if risk is None:
        return schema
    choices = []
    for basis in ("evidence", "judgment"):
        properties = dict(risk["properties"])
        properties["basis"] = {"type": "string", "enum": [basis]}
        if basis == "evidence":
            properties["evidence_ids"] = {**properties["evidence_ids"], "minItems": 1}
        else:
            del properties["evidence_ids"]
        choices.append(
            dict(
                type="object",
                properties=properties,
                required=list(properties),
                additionalProperties=False,
            )
        )
    # Express the cross-field rule in the grammar, not just a field description.
    schema["$defs"]["RiskFlag"] = {"anyOf": choices}
    return schema


def compatible_output_parameters(parameters: ModelRequestParameters) -> ModelRequestParameters:
    """Translate strict output schemas using the provider's supported schema subset.

    Args:
        parameters: Framework tool and output definitions for one request.
    Returns:
        Copied definitions; full validation remains in the local Pydantic models.
    """
    return replace(
        parameters,
        output_tools=[
            replace(tool, parameters_json_schema=_output_schema(tool.parameters_json_schema))
            if tool.strict
            else tool
            for tool in parameters.output_tools
        ],
    )


def require_complete_response(response: ModelResponse) -> None:
    """Reject incomplete output after its response and usage have been recorded.

    Args:
        response: Returned provider or replay response.
    Raises:
        LLMInvalidOutput: Generation stopped at its output-token limit.
    """
    if response.finish_reason == "length":
        raise LLMInvalidOutput("Model response reached the output token limit; draft is incomplete")


def output_errors(error: BaseException) -> list[str]:
    """Recover field-level schema failures without exposing raw input payloads.

    Args:
        error: Failure at the per-page boundary, possibly wrapping schema errors.
    Returns:
        Application errors, safe schema diagnostics, or the unexpected error type.
    """
    if isinstance(error, AcquirerEngineError):
        return [str(error)]
    cause: BaseException | None = error
    visited: set[int] = set()
    while cause is not None and id(cause) not in visited:
        visited.add(id(cause))
        if isinstance(cause, ValidationError):
            return [
                f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                for item in cause.errors(
                    include_input=False, include_context=False, include_url=False
                )
            ]
        cause = cause.__cause__ or cause.__context__
    return [type(error).__name__]
