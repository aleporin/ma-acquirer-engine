"""Freeze run inputs, verify replay compatibility, and inspect historical outcomes.

Owns: Snapshots, manifest integrity, safe run paths, and source/run identity.
Does not own: Provider calls, transcript matching, or historical code checkout.
"""

import json
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, ValidationError

from acquirer_engine.data import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError, LLMInvalidOutput
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.feedback.ranking import FeedbackPolicy
from acquirer_engine.feedback.state import FeedbackState
from acquirer_engine.llm.cost import ExecutionMode
from acquirer_engine.llm.results import RunId
from acquirer_engine.settings import Settings
from acquirer_engine.stages.select import Selection


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
    feedback: FeedbackState = Field(default_factory=FeedbackState)
    feedback_policy: FeedbackPolicy | None = None


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
            payload = snapshot.model_dump(mode="json")
            payload["settings"]["analyst"] = snapshot.settings.analyst.model_dump(
                mode="json", exclude_unset=True
            )
            stream.write(json.dumps(payload, indent=2) + "\n")
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


class ReplayManifest(BaseModel):
    """Content digests cover every required archive file."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: RunId
    sha256: dict[
        Literal["snapshot.json", "run.json", "trace.jsonl"],
        Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ]


def _checked_archive(root: Path) -> Path | None:
    path = root / "cache/replay/manifest.json"
    if not path.exists():
        return None
    try:
        manifest = ReplayManifest.model_validate_json(path.read_bytes())
        if set(manifest.sha256) != {"snapshot.json", "run.json", "trace.jsonl"}:
            raise LLMInvalidOutput("Replay manifest must cover all three archive files")
        source = (path.parent / manifest.run_id).resolve()
        if source.parent != path.parent.resolve():
            raise LLMInvalidOutput("Replay archive must remain inside the cache")
        for name, expected in manifest.sha256.items():
            file = source / name
            if file.is_symlink() or sha256(file.read_bytes()).hexdigest() != expected:
                raise LLMInvalidOutput(f"Replay checksum mismatch: {name}")
        return source
    except (OSError, ValidationError) as error:
        raise LLMInvalidOutput("Portable replay manifest or archive is unreadable") from error


def select_replay(root: Path, deps: Deps, selected: Selection) -> tuple[Path, RunSnapshot] | None:
    """Require an exact selection match before using frozen provider responses.

    Args:
        root: Current project with a committed cache and current prompts.
        deps: Current execution policy and logger.
        selected: Actual requested target, eligible history, and adjusted ranking.
    Returns:
        Historical source and snapshot, or None when no bundle is installed.
    Raises:
        LLMInvalidOutput: Corrupt or stale archive; never falls back to live calls.
    """
    source = _checked_archive(root)
    if source is None:
        return None
    snapshot = load_snapshot(source)
    if (
        snapshot.packs != selected.packs
        or snapshot.history != selected.history
        or snapshot.feedback != selected.feedback
    ):
        raise LLMInvalidOutput(
            "Portable replay has no matching target or feedback selection; "
            "use a matching historical replay or explicitly request --fresh"
        )
    if (snapshot.feedback_policy is not None or snapshot.feedback.flags) and (
        snapshot.feedback_policy != selected.feedback_policy
    ):
        raise LLMInvalidOutput(
            "Portable replay feedback policy differs; "
            "use a matching historical replay or explicitly request --fresh"
        )
    _check_policy(root, deps, snapshot)
    return source, snapshot


def _check_policy(root: Path, deps: Deps, snapshot: RunSnapshot) -> None:
    current, saved = deps.settings, snapshot.settings
    prompt = (root / "prompts" / current.analyst.prompt_file).read_text("utf-8")
    roles = {
        "sparse": current.analyst.sparse_prompt_file,
        "reviewer": current.analyst.reviewer_prompt_file
        if current.analyst.reviewer_enabled
        else None,
    }
    auxiliary = {
        role: (root / "prompts" / file).read_text("utf-8") for role, file in roles.items() if file
    }
    if (
        current.analyst != saved.analyst
        or current.evidence != saved.evidence
        or current.evaluation.prompt_version != saved.evaluation.prompt_version
        or prompt != snapshot.prompt
        or auxiliary != snapshot.auxiliary_prompts
        or any(
            current.models.roles[role] != saved.models.roles[role]
            for role in ("analyst", "escalation")
        )
    ):
        raise LLMInvalidOutput(
            "Portable replay prompt or generation policy differs; "
            "use the historical replay command for frozen inputs"
        )
