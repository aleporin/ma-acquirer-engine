"""Summarize historical purchases without exporting transaction identities.

Owns: Anonymous training aggregates and a reproducible proposal-input digest.
Does not own: Weight hypotheses, temporal validation, or production scoring.
"""

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from statistics import fmean, median, pstdev
from typing import Any

from acquirer_engine.data import Transaction
from acquirer_engine.errors import EvaluationError
from acquirer_engine.ranking.config import RankingConfig
from evals.ranking.weighting import ExperimentPolicy


def _canonical(packet: dict[str, Any]) -> bytes:
    return json.dumps(packet, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _summary(rows: Sequence[Transaction]) -> dict[str, Any]:
    sectors = Counter(row.sector for row in rows)
    years = Counter(row.deal_year for row in rows)
    sizes = sorted(row.deal_size_mm for row in rows)
    margins = sorted(row.ebitda_margin_pct for row in rows)
    closed = sum(row.outcome == "Closed" for row in rows)
    resolved = sum(row.outcome in {"Closed", "Withdrawn", "Terminated"} for row in rows)
    return {
        "deal_count": len(rows),
        "sector_count": len(sectors),
        "sector_hhi": round(math.fsum((n / len(rows)) ** 2 for n in sorted(sectors.values())), 6),
        "ev_mm_min": min(sizes),
        "ev_mm_median": median(sizes),
        "ev_mm_max": max(sizes),
        "ev_ln_population_sd": round(pstdev(math.log(size) for size in sizes), 6),
        "margin_pct_median": median(margins),
        "margin_population_cv": round(pstdev(margins) / fmean(margins), 6),
        "closed_count": closed,
        "resolved_count": resolved,
        "completion_rate": round(closed / resolved, 6) if resolved else None,
        "year_counts": {str(year): years[year] for year in sorted(years)},
    }


def _population(rows: Sequence[Transaction]) -> dict[str, Any]:
    buyers: dict[str, list[Transaction]] = defaultdict(list)
    for row in rows:
        buyers[row.acquirer].append(row)
    return {
        "buyer_count": len(buyers),
        "transaction_summary": _summary(rows) if rows else None,
        "buyers": sorted((_summary(history) for history in buyers.values()), key=_canonical),
    }


def build_packet(
    rows: Sequence[Transaction], policy: ExperimentPolicy, scoring: RankingConfig
) -> dict[str, Any]:
    """Build complete anonymous summaries from eligible proposal-period history.

    Args:
        rows: Source transactions, possibly including future or rumored deals.
        policy: Frozen proposal cutoff and candidate multiplier bounds.
        scoring: Existing feature weights; never modified by packet generation.
    Returns:
        JSON-compatible aggregates without names, identity hashes, or source rows.
    Raises:
        EvaluationError: No eligible proposal history remains.
    """
    eligible = [r for r in rows if r.deal_year <= policy.proposal_cutoff and r.outcome != "Rumored"]
    if not eligible:
        raise EvaluationError("No eligible history for the proposal packet")
    return {
        "proposal_cutoff": policy.proposal_cutoff,
        "eligible_transactions": len(eligible),
        "eligible_buyers": len({row.acquirer for row in eligible}),
        "base_weights": dict(sorted(scoring.weights.items())),
        "proposal_bounds": {
            "min_multiplier": policy.min_multiplier,
            "max_multiplier": policy.max_multiplier,
            "max_candidates": policy.max_candidates,
        },
        "populations": {
            kind: _population([row for row in eligible if row.acquirer_type == kind])
            for kind in ("Financial Sponsor", "Strategic")
        },
        "definitions": {
            "population": "All observed buyers and non-Rumored transactions through the cutoff.",
            "sector_hhi": "Sum of squared sector transaction shares on the 0-1 scale.",
            "ev": "Stated deal_size_mm in USD millions; SD uses natural logs and ddof=0.",
            "margin": "Stated margin percent; CV is population SD / mean, expressed as a ratio.",
            "completion": "Closed / (Closed + Withdrawn + Terminated); null for zero denominator.",
            "year_counts": "Eligible transactions per observed year; absent years have zero deals.",
            "buyers": "All buyer histories, sorted by aggregate statistics without identities.",
            "precision": "Derived ratios and dispersions rounded to six decimal places.",
        },
        "limitations": [
            "Singleton histories have zero observed dispersion; this is not preference evidence.",
            "All summaries describe historical purchases, not purchasing mandates or causation.",
            "Transaction summaries weight deals equally; buyer records retain sparse histories.",
        ],
    }


def packet_digest(packet: dict[str, Any]) -> str:
    """Hash canonical packet content, never buyer identifiers or source rows.

    Args:
        packet: The complete JSON-compatible proposal input.
    Returns:
        SHA-256 digest unchanged by dictionary insertion order.
    """
    return hashlib.sha256(_canonical(packet)).hexdigest()
