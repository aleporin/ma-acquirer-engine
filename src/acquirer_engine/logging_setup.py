"""Create isolated structured logging for one run.

Owns: JSON emission to stderr and a run log, and handler cleanup.
Does not own: Process-wide logging configuration or transcript storage.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO, cast

import structlog
from structlog.stdlib import BoundLogger


@contextmanager
def run_logger(
    runs_dir: Path,
    run_id: str,
    git_sha: str,
    prompt_version: str,
    stream: TextIO,
) -> Iterator[BoundLogger]:
    """Bind run context and close owned log handlers on exit.

    Args:
        runs_dir: Parent directory for per-run logs.
        run_id: Identifier created at the command boundary.
        git_sha: Evaluated source revision.
        prompt_version: Configured prompt version or unimplemented marker.
        stream: Destination for stderr events.
    Yields:
        A run-scoped logger; binding task context leaves it unchanged.
    Raises:
        OSError: The log directory or file cannot be created.
    """
    directory = runs_dir / run_id
    directory.mkdir(parents=True, exist_ok=True)
    base = logging.Logger("acquirer_engine", level=logging.INFO)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(stream),
        logging.FileHandler(directory / "log.jsonl", encoding="utf-8"),
    ]
    for handler in handlers:
        base.addHandler(handler)
    logger = cast(
        BoundLogger,
        structlog.wrap_logger(
            base,
            wrapper_class=BoundLogger,
            processors=[structlog.stdlib.add_log_level, structlog.processors.JSONRenderer()],
        ),
    ).bind(run_id=run_id, git_sha=git_sha, prompt_version=prompt_version, mode="replay")
    try:
        yield logger
    finally:
        for handler in handlers:
            base.removeHandler(handler)
            handler.close()
