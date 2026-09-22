"""Bound recognized exclusive theme claims to complete buyer-history coverage.

Owns: A conservative scope guard for the observed partial-history overclaim.
Does not own: General semantic verification or truth of complete-history claims.
"""

import re

from acquirer_engine.evidence.context import EvidenceContext
from acquirer_engine.validation.schema import AcquirerRationale, prose_sections


def theme_scope_errors(page: AcquirerRationale, context: EvidenceContext) -> list[str]:
    """Require complete own-history coverage for recognized exclusive theme prose.

    Args:
        page: Parsed prose, including the private reasoning summary.
        context: Actual core and retrieved rows available to this draft.
    Returns:
        Repairable errors requesting positive examples instead of exclusivity.
        Complete coverage lifts this scope restriction, not all semantic checks.
    """
    own_ids = {
        row.transaction_id
        for row in (*context.core.deals, *context.retrieved_deals, *context.comparable_deals)
        if row.acquirer == context.core.ranking.acquirer
    }
    if len(own_ids) == context.core.total_rows:
        return []
    themes = [tag.casefold().replace("-", " ") for tag in context.core.target.tags]
    errors = []
    for path, prose in prose_sections(page).items():
        for sentence in re.split(r"[.!?;]\s+", prose.casefold().replace("-", " ")):
            if any(theme in sentence for theme in themes) and re.search(
                r"\bonly\s+(?:through|in|on)\b", sentence
            ):
                errors.append(
                    f"{path}: exclusive theme assertion requires complete buyer history; "
                    "describe an observed positive example without claiming exclusivity"
                )
    return errors
