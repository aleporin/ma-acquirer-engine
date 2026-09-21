"""Query bounded evidence for analyst-selected questions.

Owns: Five deterministic queries and canonical closed-deal statistics.
Does not own: Model decisions or recording which results a page received.
"""

from statistics import median
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, FiniteFloat, model_validator

from acquirer_engine.data.schema import Transaction
from acquirer_engine.evidence.ids import stat_id
from acquirer_engine.evidence.pack import Statistic
from acquirer_engine.llm.config import AnalystConfig

type ToolName = Literal[
    "get_comparable_deals",
    "get_sector_stats",
    "get_adjacent_sector_activity",
    "get_sponsor_platform_history",
    "get_failed_deals",
]


class NumericBand(BaseModel):
    """Inclusive limits in the metric's canonical units."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    low: FiniteFloat
    high: FiniteFloat

    @model_validator(mode="after")
    def ordered(self) -> Self:
        """Reject reversed query ranges."""
        if self.low > self.high:
            raise ValueError("Band low must not exceed high")
        return self


class ToolResult(BaseModel):
    """A bounded view, with full-match counts and evidence IDs on every fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: ToolName
    rows: tuple[Transaction, ...]
    statistics: tuple[Statistic, ...] = ()
    total_rows: int
    truncated: bool


class EvidenceTools:
    """Read only the validated dataset available at the run's cutoff."""

    def __init__(self, rows: tuple[Transaction, ...], config: AnalystConfig) -> None:
        """Retain eligible rows and shared policy without I/O.

        Args:
            rows: History already restricted to the run cutoff.
            config: Row cap and execution policy.
        """
        self.rows = tuple(row for row in rows if row.outcome != "Rumored")
        self.config = config

    def _result(self, name: ToolName, rows: tuple[Transaction, ...]) -> ToolResult:
        selected = sorted(rows, key=lambda row: (-row.deal_year, row.transaction_id))
        return ToolResult(
            tool=name,
            rows=tuple(selected[: self.config.tool_max_rows]),
            total_rows=len(rows),
            truncated=len(rows) > self.config.tool_max_rows,
        )

    def comparable_deals(
        self,
        sector: str,
        size_band: NumericBand,
        margin_band: NumericBand | None,
        geography: str | None,
    ) -> ToolResult:
        """Find Closed comps satisfying every supplied filter.

        Args:
            sector: Exact sector label.
            size_band: EV range in millions.
            margin_band: Optional EBITDA margin percentage range.
            geography: Optional exact geography; omitted means all regions.
        Returns:
            Capped rows with their canonical stated multiples.
        """
        rows = tuple(
            r
            for r in self.rows
            if r.outcome == "Closed"
            and r.sector == sector
            and size_band.low <= r.deal_size_mm <= size_band.high
            and (margin_band is None or margin_band.low <= r.ebitda_margin_pct <= margin_band.high)
            and (geography is None or r.geography == geography)
        )
        return self._result("get_comparable_deals", rows)

    def sector_stats(self, sector: str) -> ToolResult:
        """Compute benchmarks across all Closed rows, independent of display caps.

        Args:
            sector: Exact sector label.
        Returns:
            Counts and stated multiple, margin, and bidder medians.
        """
        rows = tuple(r for r in self.rows if r.sector == sector and r.outcome == "Closed")
        values: dict[str, float] = {"closed_deal_count": len(rows)}
        if rows:
            for metric in (
                "ev_ebitda_multiple",
                "ev_revenue_multiple",
                "ebitda_margin_pct",
                "num_bidders",
            ):
                values[f"median_{metric}"] = median(getattr(row, metric) for row in rows)
        stats = tuple(
            Statistic(evidence_id=stat_id(k, f"closed-sector-{sector}"), metric=k, value=v)
            for k, v in values.items()
        )
        return self._result("get_sector_stats", rows).model_copy(update={"statistics": stats})

    def adjacent_activity(self, acquirer: str, sectors: tuple[str, ...]) -> ToolResult:
        """Return this buyer's activity in the requested adjacent sectors.

        Args:
            acquirer: Exact buyer identity.
            sectors: Sector labels selected by the analyst.
        Returns:
            Eligible capped history; no inferred sector labels.
        """
        rows = tuple(r for r in self.rows if r.acquirer == acquirer and r.sector in sectors)
        return self._result("get_adjacent_sector_activity", rows)

    def platform_history(self, acquirer: str, sector: str) -> ToolResult:
        """Return Closed sponsor platform investments in a sector.

        Args:
            acquirer: Exact buyer identity.
            sector: Requested platform sector.
        Returns:
            Financial-sponsor Platform Investment precedents only.
        """
        rows = tuple(
            r
            for r in self.rows
            if r.acquirer == acquirer
            and r.sector == sector
            and r.acquirer_type == "Financial Sponsor"
            and r.outcome == "Closed"
            and r.deal_type == "Platform Investment"
        )
        return self._result("get_sponsor_platform_history", rows)

    def failed_deals(self, acquirer: str) -> ToolResult:
        """Return Withdrawn and Terminated transactions for execution-risk analysis.

        Args:
            acquirer: Exact buyer identity.
        Returns:
            Capped failed transactions, excluding unresolved outcomes.
        """
        rows = tuple(
            r
            for r in self.rows
            if r.acquirer == acquirer and r.outcome in {"Withdrawn", "Terminated"}
        )
        return self._result("get_failed_deals", rows)
