"""Select canonical deal facts for the visible rationale tables.

Owns: Lookup of the exact precedent and comparable rows cited by each page.
Does not own: Revising prose, validating generation, or inferring investment success.
"""

from dataclasses import dataclass

from acquirer_engine.data.schema import Transaction
from acquirer_engine.llm.archive import RunSnapshot
from acquirer_engine.llm.results import PageResult


@dataclass(frozen=True)
class DealFacts:
    """Public source rows, kept separate from model-written narrative."""

    precedents: tuple[Transaction, ...]
    comparables: tuple[Transaction, ...]


def deal_facts(snapshot: RunSnapshot, page: PageResult) -> DealFacts:
    """Resolve rows after the report's evidence appendix has checked references.

    Args:
        snapshot: Frozen transaction history for this run.
        page: A page whose citations were checked by the renderer.
    Returns:
        Cited source rows, or empty tables for unavailable pages.
    """
    if page.status != "verified" or page.rationale is None:
        return DealFacts((), ())
    rows = {row.transaction_id: row for row in snapshot.history}
    return DealFacts(
        tuple(rows[item.transaction_id] for item in page.rationale.precedent_activity),
        tuple(rows[item.evidence_id] for item in page.rationale.valuation_context.comps),
    )
