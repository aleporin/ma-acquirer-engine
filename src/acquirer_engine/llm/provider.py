"""Adapt provider transport and structured output to the application boundary.

Owns: Client configuration, supported output schemas, and safe response diagnostics.
Does not own: Client lifetime, repair routing, evidence validation, or accounting.
"""

from dataclasses import replace
from typing import Any

import httpx2
from anthropic import AsyncAnthropic, transform_schema
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestParameters

from acquirer_engine.errors import AcquirerEngineError, LLMInvalidOutput
from acquirer_engine.llm.config import AnalystConfig


class AnalystClient(AsyncAnthropic):
    """Keep SDK backoff/jitter while excluding nontransient client statuses."""

    def _should_retry(self, response: httpx2.Response) -> bool:
        return response.status_code in {408, 429} or response.status_code >= 500


def create_client(
    config: AnalystConfig,
    *,
    http_client: httpx2.AsyncClient | None = None,
    api_key: str | None = None,
) -> AsyncAnthropic:
    """Build the client's complete lifecycle once before task fan-out.

    Args:
        config: Timeout and SDK retry limits.
        http_client: Optional injected transport for offline integration tests.
        api_key: Test credential override; live SDK reads its environment normally.
    Returns:
        An owned async client, to be closed by the command boundary.
    """
    return AnalystClient(
        api_key=api_key,
        http_client=http_client,
        max_retries=config.sdk_retries,
        timeout=config.request_timeout_seconds,
    )


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
