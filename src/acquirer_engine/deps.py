"""Carry references to one run's shared execution resources.

Owns: Preparation dependencies and the required resources for model stages.
Does not own: Constructing or closing resources.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from structlog.stdlib import BoundLogger

from acquirer_engine.settings import Settings

if TYPE_CHECKING:
    from acquirer_engine.factory import AnalystServices


@dataclass(frozen=True)
class Deps:
    """Settings and logging available before model resources are assembled."""

    settings: Settings
    logger: BoundLogger

    def with_runtime(self, runtime: "AnalystServices") -> "RuntimeDeps":
        """Bind prepared resources without changing this settings/logger context."""
        return RuntimeDeps(self.settings, self.logger, runtime)


@dataclass(frozen=True)
class RuntimeDeps(Deps):
    """A ready runtime required by drafting, review, and comparison summaries."""

    runtime: "AnalystServices"
