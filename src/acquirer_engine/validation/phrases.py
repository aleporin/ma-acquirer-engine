"""Detect configured boilerplate in checked rationale prose.

Owns: Case- and whitespace-normalized literal phrase matching.
Does not own: Semantic judgment or evidence verification.
"""

from acquirer_engine.validation.schema import AcquirerRationale, prose_sections


def banned_phrases(page: AcquirerRationale, phrases: tuple[str, ...]) -> list[str]:
    """Return specific field paths for configured boilerplate.

    Args:
        page: Parsed rationale.
        phrases: Forbidden phrases from configuration.
    Returns:
        Actionable validation errors.
    """
    errors = []
    for path, text in prose_sections(page).items():
        normalized = " ".join(text.casefold().split())
        for phrase in phrases:
            if " ".join(phrase.casefold().split()) in normalized:
                errors.append(f"{path}: banned phrase '{phrase}'")
    return errors
