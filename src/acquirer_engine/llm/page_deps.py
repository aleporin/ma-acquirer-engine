"""Separate shared execution resources from per-page observations.

Owns: The dependency container passed to each agent run.
Does not own: Constructing clients or selecting tools.
"""

from dataclasses import dataclass

from acquirer_engine.deps import Deps
from acquirer_engine.llm.tool_state import ToolState


@dataclass
class PageDeps:
    """One page's retrieval state with references to shared run resources."""

    shared: Deps
    state: ToolState
