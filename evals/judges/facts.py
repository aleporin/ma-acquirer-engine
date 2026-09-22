"""Present archived facts beside narrative pages for independent evaluation.

Owns: Visible section text and compact evidence summaries from frozen inputs.
Does not own: Outside research or treating a page's claims as their own evidence.
"""

import json
from collections import Counter

from acquirer_engine.data import Transaction
from acquirer_engine.errors import EvaluationError
from acquirer_engine.evidence.pack import CorePack, Statistic
from acquirer_engine.llm.tools import EvidenceTools
from acquirer_engine.replay import RunSnapshot
from acquirer_engine.validation.schema import AcquirerRationale
from evals.judges.schema import Candidate


def page_text(page: AcquirerRationale) -> str:
    """Render visible sections, excluding internal reasoning and the numeric ledger.

    Args:
        page: Validated archived rationale.
    Returns:
        Plain text suitable for both blind human reading and rubric evaluation.
    """
    sections = [f"Overview: {page.acquirer_overview}", f"Thesis: {page.strategic_fit_thesis}"]
    sections.extend(
        f"Precedent {p.transaction_id}: {p.description}" for p in page.precedent_activity
    )
    sections.append(f"Valuation: {page.valuation_context.summary}")
    sections.extend(
        f"Risk ({risk.category}; {risk.basis}): {risk.description}" for risk in page.risk_flags
    )
    sections.append(f"Conviction ({page.conviction.level}): {page.conviction.justification}")
    if page.outside_dataset_notes:
        sections.append(f"Outside dataset notes: {page.outside_dataset_notes}")
    return "\n\n".join(sections)


def candidate_summary(pack: CorePack, history: tuple[Transaction, ...]) -> Candidate:
    """Summarize recorded patterns without identifying evidence-key shortcuts."""
    own = [
        row for row in history if row.acquirer == pack.ranking.acquirer and row.outcome != "Rumored"
    ]
    summary = {
        "buyer_type": pack.ranking.acquirer_type,
        "sector_counts": dict(Counter(row.sector for row in own)),
        "geographies": dict(Counter(row.geography for row in own)),
        "recorded_statistics": {
            fact.metric: fact.value for fact in pack.statistics if "." not in fact.metric
        },
        "precedent_excerpt": [
            f"{row.target_company}, {row.deal_year}, {row.sector}, "
            f"EV ${row.deal_size_mm}M, {row.outcome}"
            for row in pack.deals
        ],
        "excerpt_truncated": pack.truncated,
    }
    return Candidate(name=pack.ranking.acquirer, summary=json.dumps(summary, sort_keys=True))


def source_facts(snapshot: RunSnapshot) -> dict[str, Transaction | Statistic]:
    """Resolve historical rows and deterministic benchmarks from the frozen population.

    Args:
        snapshot: Original source population, core packs, and query policy.
    Returns:
        Source facts; these are not assertions made by a generation or judge.
    """
    index: dict[str, Transaction | Statistic] = {
        row.transaction_id: row for row in snapshot.history
    }
    tools = EvidenceTools(snapshot.history, snapshot.settings.analyst)
    for sector in sorted({row.sector for row in snapshot.history}):
        index.update({fact.evidence_id: fact for fact in tools.sector_stats(sector).statistics})
    for pack in snapshot.packs:
        index.update({fact.evidence_id: fact for fact in pack.statistics})
    return index


def _fact_text(fact: Transaction | Statistic) -> str:
    if isinstance(fact, Statistic):
        return f"{fact.evidence_id}: {fact.metric} = {fact.value}"
    return (
        f"{fact.transaction_id}: {fact.acquirer} / {fact.target_company}; {fact.sector}, "
        f"{fact.geography}, {fact.deal_year}, {fact.outcome}; EV ${fact.deal_size_mm}M; "
        f"stated EV/EBITDA {fact.ev_ebitda_multiple}x, EV/Revenue {fact.ev_revenue_multiple}x; "
        f"EBITDA margin {fact.ebitda_margin_pct}%; {fact.num_bidders} bidders; "
        f"{fact.financing_type}; {fact.deal_type}."
    )


def evidence_text(
    page: AcquirerRationale, pack: CorePack, index: dict[str, Transaction | Statistic]
) -> str:
    """Resolve cited facts and expose the original deterministic ranking explanation.

    Args:
        page, pack, index: Archived narrative and its independent factual inputs.
    Returns:
        Compact text, retaining canonical stated values rather than rounded claims.
    Raises:
        EvaluationError: A cited fact cannot be resolved against this source.
    """
    refs = {claim.evidence_id for claim in page.claims}
    refs.update(p.transaction_id for p in page.precedent_activity)
    refs.update(comp.evidence_id for comp in page.valuation_context.comps)
    refs.update(ref for risk in page.risk_flags for ref in risk.evidence_ids)
    if refs - index.keys():
        raise EvaluationError("Cited evidence is absent from the frozen source")
    lines = [_fact_text(index[ref]) for ref in sorted(refs)]
    lines.append("Code-computed ranking: " + pack.ranking.model_dump_json())
    return "\n".join(lines)
