"""Resolve visible report facts and citations against frozen evidence.

Owns: Cited deal rows, appendix contents, and stable safe HTML anchors.
Does not own: Revising prose or deciding whether generated claims are valid.
"""

from dataclasses import dataclass
from hashlib import sha256

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import DataError
from acquirer_engine.evidence.pack import Statistic
from acquirer_engine.llm.archive import RunSnapshot
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.llm.tools import EvidenceTools


def anchor(identifier: str) -> str:
    """Return an HTML identifier independent of untrusted evidence text."""
    return "evidence-" + sha256(identifier.encode()).hexdigest()


def cited_ids(report: AnalystRun) -> set[str]:
    """Collect every visible reference from verified pages only."""
    ids: set[str] = set()
    for page in report.pages:
        rationale = page.rationale
        if page.status != "verified" or rationale is None:
            continue
        ids.update(item.transaction_id for item in rationale.precedent_activity)
        ids.update(item.evidence_id for item in rationale.valuation_context.comps)
        ids.update(item.evidence_id for item in rationale.claims)
        ids.update(ref for risk in rationale.risk_flags for ref in risk.evidence_ids)
    return ids


def appendix(
    snapshot: RunSnapshot, report: AnalystRun
) -> tuple[list[Transaction], list[Statistic]]:
    """Resolve displayed citations before writing any report files.

    Args:
        snapshot: Frozen history and code-computed core statistics.
        report: Verified pages or explicit failed outcomes.
    Returns:
        Referenced transactions and computed facts in identity order.
    Raises:
        DataError: A citation is absent from the archived evidence.
    """
    rows = {row.transaction_id: row for row in snapshot.history}
    stats = {s.evidence_id: s for pack in snapshot.packs for s in pack.statistics}
    tools = EvidenceTools(snapshot.history, snapshot.settings.analyst)
    for sector in sorted({row.sector for row in snapshot.history}):
        stats.update({s.evidence_id: s for s in tools.sector_stats(sector).statistics})
    ids = cited_ids(report)
    if missing := ids - rows.keys() - stats.keys():
        raise DataError(f"Report evidence is missing: {', '.join(sorted(missing))}")
    return (
        [rows[key] for key in sorted(ids & rows.keys())],
        [stats[key] for key in sorted(ids & stats.keys())],
    )


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
