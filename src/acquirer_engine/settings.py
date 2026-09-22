"""Load and validate run configuration once.

Owns: Typed model metadata, evaluation settings, and YAML loading.
Does not own: Client construction, environment secrets, or scoring.
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    ValidationError,
    model_validator,
)

from acquirer_engine.errors import ConfigError
from acquirer_engine.evidence.config import EvidenceConfig
from acquirer_engine.feedback.ranking import FeedbackPolicy
from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.ranking.config import BacktestConfig, RankingConfig


class ConfigModel(BaseModel):
    """Reject unknown keys and nonfinite numbers at configuration boundaries."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class PriceTier(ConfigModel):
    """Standard USD prices per million tokens for one context band."""

    max_input_tokens: PositiveInt | None
    input_usd_per_million: NonNegativeFloat
    output_usd_per_million: NonNegativeFloat
    cache_read_usd_per_million: NonNegativeFloat
    cache_write_usd_per_million: NonNegativeFloat | None = None
    cache_write_1h_usd_per_million: NonNegativeFloat | None = None
    cache_storage_usd_per_million_hour: NonNegativeFloat | None = None


class ModelSpec(ConfigModel):
    """A documented provider model and the date its prices were checked."""

    provider: Literal["anthropic", "openai", "google"]
    model_id: Annotated[str, Field(min_length=1)]
    as_of: date
    preview: bool
    source_urls: Annotated[list[HttpUrl], Field(min_length=1)]
    pricing: Annotated[list[PriceTier], Field(min_length=1)]


class ModelsConfig(ConfigModel):
    """Models available to later stages, with no client construction."""

    roles: Annotated[dict[str, ModelSpec], Field(min_length=1)]


class QualityLimits(ConfigModel):
    """Physical line limits for maintained files and Python functions."""

    max_file_lines: PositiveInt
    max_function_lines: PositiveInt


class LayerSpec(ConfigModel):
    """Stable evaluation layer identity and display name."""

    id: Annotated[int, Field(ge=0, le=6)]
    name: Annotated[str, Field(min_length=1)]


class EvalConfig(ConfigModel):
    """Select offline layers without enabling provider calls."""

    phase: Literal["p0", "p1", "p2", "p3", "p4", "p5"]
    seed: NonNegativeInt
    prompt_version: Annotated[str, Field(min_length=1)]
    quality: QualityLimits
    layers: list[LayerSpec]
    offline_layers: list[int]
    ci_layers: list[int]
    backtest: BacktestConfig

    @model_validator(mode="after")
    def validate_layers(self) -> Self:
        """Require all seven identities and unique offline subsets.

        Returns:
            This validated configuration.
        Raises:
            ValueError: Layer identities or subsets are inconsistent.
        """
        ids = [layer.id for layer in self.layers]
        if sorted(ids) != list(range(7)):
            raise ValueError("Define each layer from 0 through 6 exactly once")
        allowed = set(ids) if self.phase == "p5" else set(ids) - {4}
        for selection in (self.offline_layers, self.ci_layers):
            if not selection or len(selection) != len(set(selection)):
                raise ValueError("Layer selection must be nonempty and unique")
            if not set(selection) <= allowed:
                raise ValueError("Offline selections cannot include the live judge layer")
        if 4 in self.ci_layers:
            raise ValueError("CI cannot include the live judge layer")
        return self


class Settings(ConfigModel):
    """The configuration snapshot injected into one run."""

    models: ModelsConfig
    scoring: RankingConfig
    evaluation: EvalConfig
    evidence: EvidenceConfig
    analyst: AnalystConfig


def _load_yaml[T: BaseModel](path: Path, schema: type[T]) -> T:
    try:
        return schema.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise ConfigError(f"Invalid or unreadable configuration: {path.name}") from error


def load_settings(config_dir: Path) -> Settings:
    """Read each YAML file once and return a validated snapshot.

    Args:
        config_dir: Directory containing the configuration files.
    Returns:
        Validated configuration, without reading environment variables.
    Raises:
        ConfigError: A file is missing, malformed, or violates its schema.
    """
    return Settings(
        analyst=_load_yaml(config_dir / "analyst.yaml", AnalystConfig),
        evidence=_load_yaml(config_dir / "evidence.yaml", EvidenceConfig),
        models=_load_yaml(config_dir / "models.yaml", ModelsConfig),
        scoring=_load_yaml(config_dir / "scoring.yaml", RankingConfig),
        evaluation=_load_yaml(config_dir / "eval.yaml", EvalConfig),
    )


def load_feedback_policy(config_dir: Path) -> FeedbackPolicy:
    """Load the product-only feedback policy independently of historical settings.

    Args:
        config_dir: Project configuration directory.
    Returns:
        Validated maximum similarity penalty.
    Raises:
        ConfigError: The file is missing or invalid.
    """
    return _load_yaml(config_dir / "feedback.yaml", FeedbackPolicy)
