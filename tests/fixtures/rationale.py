"""Build independently specified rationale and evidence examples.

Owns: Small synthetic examples with known numeric facts.
Does not own: Production generation or sampling the source CSV.
"""

from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.evidence.pack import build_core_pack
from acquirer_engine.settings import Settings
from tests.evidence.test_pack import pack_inputs
from tests.fixtures.ranking import transaction


def evidence_context(settings: Settings) -> EvidenceContext:
    """Supply a buyer core and a separately retrieved closed comp."""
    history, ranking, target = pack_inputs(settings)
    core = build_core_pack(history, ranking, target, settings.evidence.pack)
    comp = transaction(10, acquirer="Comparable Buyer", ev_ebitda_multiple=13.64)
    return EvidenceContext(core=core, comparable_deals=(comp,))


def rationale_payload() -> dict[str, object]:
    """Describe fixture facts without deriving claims from the verifier."""
    return {
        "reasoning": "Use the own-history activity and separately retrieved valuation comp.",
        "acquirer_overview": "The buyer has 4 recorded deals.",
        "strategic_fit_thesis": "Services experience supports a regional integration thesis.",
        "precedent_activity": [
            {
                "transaction_id": "MA-2020-0001",
                "description": "A Services precedent at $200M EV.",
            }
        ],
        "valuation_context": {
            "summary": "The closed comp has a stated EV/EBITDA of 13.6x and EV/Revenue of 2x.",
            "comps": [{"evidence_id": "MA-2020-0010"}],
        },
        "risk_flags": [
            {
                "category": "integration_complexity",
                "description": "Operating integration may be difficult.",
                "basis": "judgment",
                "evidence_ids": [],
            },
            {
                "category": "financing_capacity",
                "description": "Recorded deal size does not prove funding capacity.",
                "basis": "evidence",
                "evidence_ids": ["MA-2020-0001"],
            },
        ],
        "conviction": {
            "level": "High",
            "justification": "History supports interest, with funding uncertain.",
        },
        "outside_dataset_notes": None,
        "claims": [
            {"value": 4, "metric": "deal_count", "evidence_id": "stat:deal_count:Buyer%20A"},
            {"value": 200, "metric": "deal_size_mm", "evidence_id": "MA-2020-0001"},
            {"value": 13.6, "metric": "ev_ebitda_multiple", "evidence_id": "MA-2020-0010"},
            {"value": 2, "metric": "ev_revenue_multiple", "evidence_id": "MA-2020-0010"},
        ],
    }
