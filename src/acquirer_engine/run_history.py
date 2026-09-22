"""Read a compact inventory of completed product runs.

Owns: Historical outcome metadata independent of current output schemas.
Does not own: Executing replay, modifying archives, or loading credentials.
"""

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, NonNegativeFloat, ValidationError

from acquirer_engine.errors import EvaluationError, LLMInvalidOutput
from acquirer_engine.llm.cost import ExecutionMode
from acquirer_engine.llm.results import RunId


class PageStatus(BaseModel):
    """List status without reparsing historical rationale payloads."""

    status: Literal["verified", "failed"]


class CallCost(BaseModel):
    """Recorded spend in the original run's execution mode."""

    cost_usd: NonNegativeFloat


class RunSummary(BaseModel):
    """Stable metadata used by the run-history command."""

    run_id: RunId
    mode: ExecutionMode
    git_sha: str
    source_dirty: bool = False
    prompt_version: str
    latency_seconds: NonNegativeFloat
    replay_of: RunId | None = None
    pages: list[PageStatus]
    calls: list[CallCost]


def list_runs(root: Path) -> list[RunSummary]:
    """List completed product artifacts in file creation order.

    Args:
        root: Project containing a runs directory.
    Returns:
        Compact observations; evaluation-only log directories are excluded.
    Raises:
        LLMInvalidOutput: A completed run artifact is malformed or misidentified.
    """
    records = []
    for path in sorted((root / "runs").glob("*/run.json"), key=lambda p: p.stat().st_mtime):
        try:
            record = RunSummary.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as error:
            raise LLMInvalidOutput(f"Invalid run archive: {path.parent.name}") from error
        if record.run_id != path.parent.name:
            raise LLMInvalidOutput("Run archive identity differs from its directory")
        records.append(record)
    return records


def git_state(root: Path) -> tuple[str, bool]:
    """Read source identity and dirty state for a recorded execution.

    Args:
        root: Repository containing the code being run.
    Returns:
        Commit SHA and whether tracked or untracked files differ.
    Raises:
        EvaluationError: The directory has no usable base commit.
    """
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
        changes = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise EvaluationError("Evaluation requires a repository with a base commit") from error
    return revision, bool(changes.strip())
