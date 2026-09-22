"""Build small transaction fixtures with explicit overrides.

Owns: Synthetic data used by numeric tests.
Does not own: Source dataset sampling.
"""

from acquirer_engine.data import Transaction


def transaction(number: int = 1, **changes: object) -> Transaction:
    """Create a valid synthetic transaction, replacing only requested fields."""
    year = changes.get("deal_year", 2020)
    fields: dict[str, object] = {
        "transaction_id": f"MA-{year}-{number:04d}",
        "target_company": f"Target {number}",
        "acquirer": "Buyer A",
        "sector": "Services",
        "deal_year": year,
        "deal_quarter": "Q1",
        "deal_type": "Strategic Acquisition",
        "geography": "Northeast",
        "financing_type": "All Cash",
        "deal_size_mm": 200.0,
        "target_revenue_mm": 100.0,
        "target_ebitda_mm": 20.0,
        "ebitda_margin_pct": 20.0,
        "revenue_growth_pct": 10.0,
        "ev_ebitda_multiple": 10.0,
        "ev_revenue_multiple": 2.0,
        "synergy_pct_of_deal": 5.0,
        "outcome": "Closed",
        "strategic_rationale_tags": "Scale|Geographic Expansion",
        "num_bidders": 2,
        "days_to_close": 100,
        "acquirer_type": "Strategic",
        "target_ownership_pre": "Private",
    }
    fields.update(changes)
    return Transaction.model_validate(fields)
