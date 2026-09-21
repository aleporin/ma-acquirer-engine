"""Measure known data inconsistencies without repairing them.

Owns: Aggregate quality counts using explicit comparison tolerances.
Does not own: Scoring exclusions, imputation, or valuation selection.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from acquirer_engine.data.schema import Transaction


class QualityReport(BaseModel):
    """Counts of observed inconsistencies and expected missingness."""

    model_config = ConfigDict(frozen=True)
    rows: int
    acquirers: int
    multiple_mismatches: int
    margin_mismatches: int
    sponsor_deal_type_conflicts: int
    strategic_deal_type_conflicts: int
    rumored: int
    null_days_to_close: int


def quality_report(
    rows: Sequence[Transaction], *, multiple_tolerance: float, margin_tolerance: float
) -> QualityReport:
    """Measure discrepancies against canonical stated values.

    Args:
        rows: Validated transactions.
        multiple_tolerance: Relative difference allowed against the stated multiple.
        margin_tolerance: Absolute percentage-point margin difference allowed.
    Returns:
        Aggregate counts with no raw transaction values.
    """
    return QualityReport(
        rows=len(rows),
        acquirers=len({row.acquirer for row in rows}),
        multiple_mismatches=sum(
            abs(row.deal_size_mm / row.target_ebitda_mm - row.ev_ebitda_multiple)
            / row.ev_ebitda_multiple
            > multiple_tolerance
            for row in rows
        ),
        margin_mismatches=sum(
            abs(row.target_ebitda_mm / row.target_revenue_mm * 100 - row.ebitda_margin_pct)
            > margin_tolerance
            for row in rows
        ),
        sponsor_deal_type_conflicts=sum(
            row.acquirer_type == "Financial Sponsor"
            and row.deal_type in {"Strategic Acquisition", "Merger of Equals"}
            for row in rows
        ),
        strategic_deal_type_conflicts=sum(
            row.acquirer_type == "Strategic"
            and row.deal_type in {"Leveraged Buyout", "Platform Investment"}
            for row in rows
        ),
        rumored=sum(row.outcome == "Rumored" for row in rows),
        null_days_to_close=sum(row.days_to_close is None for row in rows),
    )
