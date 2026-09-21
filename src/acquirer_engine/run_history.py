"""Read a compact inventory of completed product runs.

Owns: Historical outcome metadata independent of current output schemas.
Does not own: Executing replay, modifying archives, or loading credentials.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, NonNegativeFloat, ValidationError

from acquirer_engine.errors import LLMInvalidOutput
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
