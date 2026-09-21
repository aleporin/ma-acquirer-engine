"""Resolve facts from core context and separately retrieved comparable deals.

Owns: Evidence lookup and conflict detection across trusted input snapshots.
Does not own: Retrieval queries or acceptance of rationale claims.
"""

from pydantic import BaseModel, ConfigDict

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import EvidenceError
from acquirer_engine.evidence.pack import CorePack, Statistic


class EvidenceContext(BaseModel):
    """Host-supplied context; the rationale cannot declare its own evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    core: CorePack
    comparable_deals: tuple[Transaction, ...] = ()

    def index(self) -> dict[str, Transaction | Statistic]:
        """Resolve IDs only within facts available to this page.

        Returns:
            An index over retained core facts and retrieved comps.
        Raises:
            EvidenceError: An ID refers to conflicting facts.
        """
        evidence: dict[str, Transaction | Statistic] = {}
        items: tuple[Transaction | Statistic, ...] = (
            *self.core.deals,
            *self.core.statistics,
            *self.comparable_deals,
        )
        for item in items:
            key = item.transaction_id if isinstance(item, Transaction) else item.evidence_id
            if key in evidence and evidence[key] != item:
                raise EvidenceError(f"conflicting evidence for {key}")
            evidence[key] = item
        return evidence
