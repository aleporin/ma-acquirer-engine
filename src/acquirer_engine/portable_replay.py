"""Select a committed response archive only for its recorded inputs.

Owns: Manifest integrity and target, feedback, prompt, and policy compatibility.
Does not own: Replaying requests or constructing a provider client.
"""

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from acquirer_engine.deps import Deps
from acquirer_engine.errors import LLMInvalidOutput
from acquirer_engine.llm.archive import RunSnapshot, load_snapshot
from acquirer_engine.llm.results import RunId
from acquirer_engine.selection import Selection


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
