"""Write local replayable analyst transcripts.

Owns: Append-only request, response, tool, and validation trace events.
Does not own: Info-level logging or remote telemetry.
"""

import json
from pathlib import Path

from pydantic_core import to_jsonable_python


class TraceWriter:
    """A single local trace sink injected into one run."""

    def __init__(self, path: Path) -> None:
        """Create the parent directory for this run's transcript."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def write(self, event: str, acquirer: str, **values: object) -> None:
        """Append one event synchronously, without interleaving task writes.

        Args:
            event: Stable event name.
            acquirer: Page identity.
            values: Replay data; never credentials or request headers.
        """
        payload = to_jsonable_python({"event": event, "acquirer": acquirer, **values})
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True) + "\n")
