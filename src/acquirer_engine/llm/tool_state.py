"""Track exactly which tool evidence an analyst has received.

Owns: Per-page retrieval state and distinct model tool-round enforcement.
Does not own: Query execution or provider calls.
"""

from dataclasses import dataclass, field

from acquirer_engine.errors import BudgetExceeded
from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.tools import ToolResult


@dataclass
class ToolState:
    """Mutable state belongs to one page; shared clients remain outside it."""

    core: CorePack
    max_rounds: int
    rounds: set[tuple[int, int]] = field(default_factory=set)
    results: list[ToolResult] = field(default_factory=list)
    generation: int = 0
    claims_total: int = 0
    claims_verified: int = 0

    def record(self, step: int, result: ToolResult) -> None:
        """Add only results within the bounded tool loop.

        Args:
            step: Model-response step that requested the tool.
            result: The rows actually returned, excluding truncated matches.
        Raises:
            BudgetExceeded: Another tool round would exceed policy.
        """
        key = (self.generation, step)
        if key not in self.rounds and len(self.rounds) >= self.max_rounds:
            raise BudgetExceeded("Maximum tool rounds exceeded")
        self.rounds.add(key)
        self.results.append(result)

    def context(self) -> EvidenceContext:
        """Build validation context without inventing retrieval provenance.

        Returns:
            Core plus only tool-returned rows and computed statistics.
        """
        return EvidenceContext(
            core=self.core,
            comparable_deals=tuple(
                row
                for result in self.results
                if result.tool == "get_comparable_deals"
                for row in result.rows
            ),
            retrieved_deals=tuple(
                row
                for result in self.results
                if result.tool != "get_comparable_deals"
                for row in result.rows
            ),
            statistics=tuple(stat for result in self.results for stat in result.statistics),
        )
