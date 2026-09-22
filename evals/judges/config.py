"""Load the independent judge policy without reading credentials.

Owns: Judge limits, versioned prompt selection, and calibration thresholds.
Does not own: Analyst policy or model pricing metadata.
"""

from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    ValidationError,
    model_validator,
)

from acquirer_engine.errors import ConfigError
from acquirer_engine.settings import ConfigModel
from evals.judges.schema import Dimension


class JudgeConfig(ConfigModel):
    """Explicit settings frozen into every judge plan."""

    version: str
    roles: tuple[str, str]
    seed: NonNegativeInt
    candidate_count: PositiveInt
    calibration_runs: PositiveInt
    bootstrap_samples: PositiveInt
    confidence: Annotated[float, Field(gt=0, lt=1)]
    identification_accuracy_min: Annotated[float, Field(ge=0, le=1)]
    kappa_min: Annotated[float, Field(ge=-1, le=1)]
    concurrency: PositiveInt
    max_output_tokens: PositiveInt
    request_overhead_tokens: PositiveInt
    sdk_retries: NonNegativeInt
    request_timeout_seconds: PositiveFloat
    run_timeout_seconds: PositiveFloat
    max_run_usd: PositiveFloat
    openai_reasoning_effort: Literal["low", "medium", "high"]
    google_thinking_level: Literal["LOW", "HIGH"]
    identification_prompt: str
    rubric_prompts: dict[Dimension, str]

    @model_validator(mode="after")
    def check_contract(self) -> Self:
        if len(set(self.roles)) != len(self.roles) or set(self.rubric_prompts) != set(Dimension):
            raise ValueError("Require independent roles and every rubric dimension")
        for name in (self.identification_prompt, *self.rubric_prompts.values()):
            if Path(name).name != name or not name.endswith(".md"):
                raise ValueError("Judge prompts must be local Markdown filenames")
        return self


def load_judge_config(path: Path) -> JudgeConfig:
    """Read a typed judge policy independently of historical generation settings.

    Args:
        path: Judge YAML file.
    Returns:
        Validated policy, with no environment or provider access.
    Raises:
        ConfigError: Configuration is missing or invalid.
    """
    try:
        return JudgeConfig.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise ConfigError("Invalid or unreadable judge configuration") from error
