"""Define execution policy for the analyst stage.

Owns: Typed model, tool, cache, concurrency, and measurement settings.
Does not own: Loading secrets or constructing clients.
"""

from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveFloat, PositiveInt


class AnalystConfig(BaseModel):
    """Settings supplied once from analyst.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    prompt_file: str
    schema_version: str
    max_tool_rounds: PositiveInt
    tool_max_rows: PositiveInt
    max_output_tokens: PositiveInt
    concurrency: PositiveInt
    request_timeout_seconds: PositiveFloat
    sdk_retries: NonNegativeInt
    output_retries: NonNegativeInt
    max_repairs: NonNegativeInt = 0
    temperature: float | None
    latency_target_seconds: PositiveFloat
    stability_runs: PositiveInt
    distinct_ngram_words: PositiveInt
