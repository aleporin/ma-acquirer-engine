"""Define, persist, and read evaluation scorecards.

Owns: Scorecard validation, immutable run artifacts, and Markdown summaries.
Does not own: Executing graders or deciding metric regressions.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    ValidationError,
    model_validator,
)

from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import ModelsConfig


class Record(BaseModel):
    """Reject extra fields and nonfinite numbers in evaluation artifacts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class RunInfo(Record):
    """Identity of the evaluated code and the invocation."""

    git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_dirty: bool = False
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    created_at: AwareDatetime


class Metric(Record):
    """One measurement and its improvement direction."""

    value: FiniteFloat
    direction: Literal["higher", "lower"]


class LayerResult(Record):
    """An explicit status for one layer, with no invented measurements."""

    id: Annotated[int, Field(ge=0, le=6)]
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    selected: bool
    status: Literal["not_implemented", "passed", "failed"]
    metrics: dict[str, Metric] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_measurements(self) -> Self:
        """Reject measurements presented by a stub.

        Returns:
            This validated layer.
        Raises:
            ValueError: An unimplemented layer contains a metric.
        """
        if self.status == "not_implemented" and self.metrics:
            raise ValueError("Unimplemented layers cannot contain measured metrics")
        return self


class Scorecard(Record):
    """Portable evaluation results with configuration and source provenance."""

    schema_version: Literal[1] = 1
    phase: Annotated[str, Field(pattern=r"^p[0-7]$")]
    mode: Literal["replay"]
    run: RunInfo
    seed: int
    prompt_version: str
    config_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    models: ModelsConfig
    requested_layers: list[int]
    layers: list[LayerResult]

    @model_validator(mode="after")
    def validate_inventory(self) -> Self:
        """Require a complete layer inventory and consistent selection.

        Returns:
            This validated scorecard.
        Raises:
            ValueError: Layers are duplicated, missing, or selected inconsistently.
        """
        if sorted(layer.id for layer in self.layers) != list(range(7)):
            raise ValueError("A scorecard must contain each layer exactly once")
        selected = sorted(layer.id for layer in self.layers if layer.selected)
        if not selected or selected != sorted(self.requested_layers):
            raise ValueError("Requested layers must match the selected results")
        return self


def _summary(card: Scorecard) -> str:
    lines = [
        f"# {card.phase} evaluation",
        "",
        f"Evaluated revision: {card.run.git_sha}",
        f"Source dirty: {card.run.source_dirty}",
        f"Run: {card.run.run_id} | Mode: {card.mode} | Seed: {card.seed}",
        f"Configuration SHA-256: {card.config_sha256}",
        "",
        "| Layer | Name | Selected | Status |",
        "| --- | --- | --- | --- |",
    ]
    for layer in sorted(card.layers, key=lambda result: result.id):
        lines.append(f"| {layer.id} | {layer.name} | {layer.selected} | {layer.status} |")
    lines.extend(["", "| Layer | Metric | Value | Direction |", "| --- | --- | --- | --- |"])
    for layer in card.layers:
        for name, metric in sorted(layer.metrics.items()):
            lines.append(f"| {layer.id} | {name} | {metric.value:.6f} | {metric.direction} |")
    lines.extend(["", "Unimplemented layers have no quality measurements.", ""])
    return "\n".join(lines)


def write_scorecard(
    card: Scorecard, results_dir: Path, *, artifacts: dict[str, str] | None = None
) -> Path:
    """Publish JSON and Markdown together without replacing prior results.

    Args:
        card: Validated results and provenance.
        results_dir: Parent directory for revision-specific results.
        artifacts: Related output files published in the same atomic bundle.
    Returns:
        Path to scorecard.json.
    Raises:
        EvaluationError: Results already exist or cannot be written.
    """
    for name in artifacts or {}:
        if Path(name).name != name or name in {"", ".", "..", "scorecard.json", "summary.md"}:
            raise EvaluationError("Invalid supplementary artifact filename")
    directory = results_dir / f"{card.phase}-{card.run.git_sha}"
    if directory.exists():
        raise EvaluationError(f"Scorecard directory already exists: {directory}")
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".scorecard-", dir=results_dir) as temporary:
            staging = Path(temporary) / "result"
            staging.mkdir()
            (staging / "scorecard.json").write_text(card.model_dump_json(indent=2) + "\n")
            (staging / "summary.md").write_text(_summary(card), encoding="utf-8")
            for name, content in (artifacts or {}).items():
                (staging / name).write_text(content, encoding="utf-8")
            staging.rename(directory)
    except OSError as error:
        raise EvaluationError(f"Could not write scorecard: {directory}") from error
    return directory / "scorecard.json"


def read_scorecard(path: Path) -> Scorecard:
    """Read a scorecard through the same boundary schema used for writing.

    Args:
        path: JSON scorecard path.
    Returns:
        Validated scorecard.
    Raises:
        EvaluationError: The artifact cannot be read or is invalid.
    """
    try:
        return Scorecard.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as error:
        raise EvaluationError(f"Invalid or unreadable scorecard: {path}") from error
