"""Verify structured rationale against available evidence.

Owns: Numeric truth, reference provenance, conviction, and composed guardrails.
Does not own: Evidence retrieval, prose judgment, or repair routing.
"""

from pydantic import ValidationError

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import ValidationFailure
from acquirer_engine.evidence.config import ValidationConfig
from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.evidence.pack import Statistic
from acquirer_engine.validation.numbers import scan_numbers
from acquirer_engine.validation.prose import (
    banned_phrases,
    sector_margin_errors,
    theme_scope_errors,
)
from acquirer_engine.validation.schema import AcquirerRationale, Claim


def _claim_errors(
    claim: Claim, index: dict[str, Transaction | Statistic], tolerance: float
) -> list[str]:
    item = index.get(claim.evidence_id)
    prefix = f"claims[{claim.evidence_id}:{claim.metric}]"
    if item is None:
        return [f"{prefix}: unknown evidence"]
    if isinstance(item, Statistic):
        value = item.value if item.metric == claim.metric else None
    else:
        value = item.model_dump().get(claim.metric)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return [f"{prefix}: unknown numeric metric"]
    discrete = isinstance(value, int) or (
        claim.metric.endswith("_count") or claim.metric == "relevant_deals"
    )
    allowed = 0 if discrete else tolerance
    if abs(claim.value - value) > allowed:
        return [f"{prefix}: value mismatch (claimed {claim.value}, evidence {value})"]
    return []


def _reference_errors(
    page: AcquirerRationale, context: EvidenceContext, ids: set[str]
) -> list[str]:
    errors = []
    own = {
        row.transaction_id
        for row in (*context.core.deals, *context.retrieved_deals)
        if row.acquirer == context.core.ranking.acquirer
    }
    for precedent in page.precedent_activity:
        if precedent.transaction_id not in own:
            errors.append(
                f"precedent_activity: unknown own-history evidence {precedent.transaction_id}"
            )
    for risk in page.risk_flags:
        errors.extend(
            f"risk_flags: unknown evidence {key}" for key in risk.evidence_ids if key not in ids
        )
    retrieved = {row.transaction_id: row for row in context.comparable_deals}
    for comp in page.valuation_context.comps:
        row = retrieved.get(comp.evidence_id)
        if row is None or row.outcome != "Closed":
            errors.append(f"valuation_context: {comp.evidence_id} requires a retrieved Closed comp")
        metrics = {claim.metric for claim in page.claims if claim.evidence_id == comp.evidence_id}
        if not {"ev_ebitda_multiple", "ev_revenue_multiple"} <= metrics:
            errors.append(f"valuation_context: {comp.evidence_id} requires stated multiple claims")
    if page.conviction.level != context.core.ranking.conviction:
        errors.append("conviction: level differs from computed conviction")
    return errors


def validate_rationale(
    payload: object, context: EvidenceContext, config: ValidationConfig
) -> AcquirerRationale:
    """Parse and verify a rationale, returning specific failures for repair.

    Args:
        payload: Untrusted structured output.
        context: Host-supplied core facts and separately retrieved comps.
        config: Section limits, rounding tolerance, and banned phrases.
    Returns:
        The verified structured rationale.
    Raises:
        ValidationFailure: Schema, factual, reference, or prose checks fail.
        EvidenceError: Supplied facts conflict before output validation.
    """
    index = context.index()
    try:
        page = AcquirerRationale.model_validate(payload, context=config)
    except ValidationError as error:
        messages = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()]
        raise ValidationFailure(messages) from error
    errors = [
        message
        for claim in page.claims
        for message in _claim_errors(claim, index, config.rounding_tolerance)
    ]
    errors.extend(_reference_errors(page, context, set(index)))
    errors.extend(scan_numbers(page, set(index), config.rounding_tolerance))
    errors.extend(banned_phrases(page, config.banned_phrases))
    errors.extend(sector_margin_errors(page, context))
    errors.extend(theme_scope_errors(page, context))
    if errors:
        raise ValidationFailure(errors)
    return page


def verified_claim_count(
    page: AcquirerRationale, context: EvidenceContext, config: ValidationConfig
) -> int:
    """Count true numeric claims independently of whole-page acceptance.

    Args:
        page: Schema-valid draft, including drafts later rejected by guardrails.
        context: Only evidence actually available to this draft.
        config: Shared numeric rounding policy.
    Returns:
        Claims whose reference, metric, and value all verify.
    """
    index = context.index()
    return sum(not _claim_errors(claim, index, config.rounding_tolerance) for claim in page.claims)
