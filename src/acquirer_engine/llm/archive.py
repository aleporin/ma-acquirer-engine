"""Freeze the inputs needed to replay a particular analyst run.

Owns: Versioned input snapshots, safe run selection, and immutable snapshot writes.
Does not own: Provider responses, execution, secrets, or historical code checkout.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import LLMInvalidOutput
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.results import RunId
from acquirer_engine.settings import Settings


class RunSnapshot(BaseModel):
    """Actual input values, independent of later edits to project files."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    run_id: RunId
    git_sha: str
    source_dirty: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_source: Literal["captured", "reconstructed"] = "captured"
    settings: Settings
    prompt: str
    auxiliary_prompts: dict[str, str] = Field(default_factory=dict)
    history: tuple[Transaction, ...]
    packs: tuple[CorePack, ...]


def run_directory(root: Path, run_id: str) -> Path:
    """Resolve one full run ID without allowing traversal outside runs.

    Args:
        root: Project directory containing run archives.
        run_id: Complete lowercase hexadecimal run identity.
    Returns:
        The selected local run directory.
    Raises:
        LLMInvalidOutput: The identifier or resolved path is unsafe.
    """
    if len(run_id) != 32 or any(char not in "0123456789abcdef" for char in run_id):
        raise LLMInvalidOutput("Invalid archive run ID; use the full ID from acquirers runs")
    runs = (root / "runs").resolve()
    directory = (runs / run_id).resolve()
    if directory.parent != runs:
        raise LLMInvalidOutput("Invalid archive location")
    return directory


def save_snapshot(directory: Path, snapshot: RunSnapshot) -> None:
    """Save inputs before execution, refusing to overwrite an existing archive.

    Args:
        directory: New run directory.
        snapshot: Settings, prompt, history, and prepared evidence for this run.
    Raises:
        LLMInvalidOutput: Directory identity differs or a snapshot already exists.
        OSError: Snapshot cannot be persisted.
    """
    if directory.name != snapshot.run_id:
        raise LLMInvalidOutput("Archive snapshot identity differs from its directory")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with (directory / "snapshot.json").open("x", encoding="utf-8") as stream:
            stream.write(snapshot.model_dump_json(indent=2) + "\n")
    except FileExistsError as error:
        raise LLMInvalidOutput("Archive snapshot already exists; use a new run ID") from error


def load_snapshot(directory: Path) -> RunSnapshot:
    """Load saved inputs without consulting current project configuration.

    Args:
        directory: Selected historical run directory.
    Returns:
        Original settings and input values.
    Raises:
        LLMInvalidOutput: The snapshot is absent, invalid, or belongs to another run.
    """
    try:
        snapshot = RunSnapshot.model_validate_json((directory / "snapshot.json").read_bytes())
    except (OSError, ValidationError) as error:
        raise LLMInvalidOutput("Run archive has no valid input snapshot") from error
    if snapshot.run_id != directory.name:
        raise LLMInvalidOutput("Archive snapshot identity differs from its directory")
    return snapshot
