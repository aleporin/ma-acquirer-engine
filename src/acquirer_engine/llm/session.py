"""Retain one page's evidence and conversation until portfolio review finishes.

Owns: In-memory continuation state scoped to one run and buyer.
Does not own: Provider resources, persistence, or recovery policy.
"""

from dataclasses import dataclass

from pydantic_ai.messages import ModelMessage

from acquirer_engine.llm.tool_state import ToolState


@dataclass
class PageSession:
    """A revision reuses evidence already retrieved for the original draft."""

    state: ToolState
    messages: list[ModelMessage]
