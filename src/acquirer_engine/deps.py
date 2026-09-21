"""Carry the dependencies used by the offline harness.

Owns: References to one run's settings and logger.
Does not own: Dependency construction or future provider resources.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from structlog.stdlib import BoundLogger

from acquirer_engine.settings import Settings

if TYPE_CHECKING:
    from acquirer_engine.llm.analyst import AnalystServices


@dataclass(frozen=True)
class Deps:
    """Dependencies constructed at the command boundary."""

    settings: Settings
    logger: BoundLogger
    runtime: "AnalystServices | None" = None
