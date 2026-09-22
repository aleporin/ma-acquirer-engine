"""Carry references to one run's shared execution resources.

Owns: Settings, logger, and the optional analyst runtime.
Does not own: Constructing or closing resources.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from structlog.stdlib import BoundLogger

from acquirer_engine.settings import Settings

if TYPE_CHECKING:
    from acquirer_engine.bootstrap import AnalystServices


@dataclass(frozen=True)
class Deps:
    """Dependencies constructed at the command boundary."""

    settings: Settings
    logger: BoundLogger
    runtime: "AnalystServices | None" = None
