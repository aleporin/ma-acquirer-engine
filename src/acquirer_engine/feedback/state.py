"""Persist canonical buyer flags without losing existing user feedback.

Owns: Typed feedback state and locked atomic local updates.
Does not own: Deciding buyer similarity or silently correcting unknown names.
"""

import fcntl
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from acquirer_engine.errors import DataError


class BuyerFlag(BaseModel):
    """A user-supplied exclusion with a nonempty reason."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    acquirer: Annotated[str, Field(min_length=1)]
    reason: Annotated[str, Field(min_length=1)]


class FeedbackState(BaseModel):
    """One exclusion per exact dataset identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    flags: tuple[BuyerFlag, ...] = ()

    @model_validator(mode="after")
    def unique_buyers(self) -> Self:
        """Reject ambiguous duplicate exclusions in manually edited state."""
        if len({f.acquirer.casefold() for f in self.flags}) != len(self.flags):
            raise ValueError("Duplicate feedback buyer")
        return self


def load_feedback(path: Path) -> FeedbackState:
    """Return empty feedback only when no saved state exists.

    Args:
        path: Project-local state file.
    Returns:
        Validated saved exclusions.
    Raises:
        DataError: Existing state cannot be read or parsed.
    """
    try:
        return FeedbackState.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return FeedbackState()
    except (OSError, ValidationError) as error:
        raise DataError("Invalid or unreadable feedback state; preserve and repair it") from error


def save_flag(path: Path, buyer: str, reason: str, known: set[str]) -> FeedbackState:
    """Canonicalize one exclusion, then atomically update under a file lock.

    Args:
        path: Project-local feedback file.
        buyer, reason: Explicit user input.
        known: Buyer names from the current dataset.
    Returns:
        Complete updated feedback state, sorted by buyer.
    Raises:
        DataError: Unknown buyer or corrupt existing feedback.
        ValidationError: Empty reason.
    """
    matches = [name for name in known if name.casefold() == buyer.strip().casefold()]
    if len(matches) != 1:
        raise DataError(f"Unknown or ambiguous acquirer: {buyer}")
    flag = BuyerFlag(acquirer=matches[0], reason=reason)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = {item.acquirer: item for item in load_feedback(path).flags}
        saved[flag.acquirer] = flag
        state = FeedbackState(flags=tuple(saved[key] for key in sorted(saved)))
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(state.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return state
