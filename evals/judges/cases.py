"""Prepare masked identification inputs without exposing expected answers.

Owns: Corpus sealing, name/reference masking, and seeded candidate permutations.
Does not own: Reading generation archives or calling judges.
"""

import html
import json
import re
from dataclasses import dataclass
from random import Random
from urllib.parse import quote, quote_plus

from pydantic import ValidationError

from acquirer_engine.errors import EvaluationError
from evals.judges.schema import Case, Corpus, corpus_digest


def seal_corpus(cases: list[Case], seed: int) -> Corpus:
    """Freeze case contents and fail closed on duplicate identities.

    Args:
        cases: Explicitly selected archived page cases.
        seed: Recorded shuffle seed.
    Returns:
        A digest-verified corpus.
    Raises:
        EvaluationError: The selection is invalid.
    """
    ordered = tuple(sorted(cases, key=lambda case: case.case_id))
    try:
        return Corpus(cases=ordered, seed=seed, digest=corpus_digest(ordered, seed))
    except ValidationError as error:
        raise EvaluationError(str(error)) from error


def mask_page(page: str, names: list[str]) -> str:
    """Remove buyer names and machine references that reveal identity directly.

    Args:
        page: Visible narrative, excluding internal reasoning and claim ledgers.
        names: Candidate names, including encoded forms present in references.
    Returns:
        Narrative retaining substantive numbers and named precedent descriptions.
    """
    masked = re.sub(r"stat:[^\s\]\[(){}<>\"'`,;]+|\bMA-\d{4}-\d{4}\b", "[reference]", page)
    variants = {
        variant
        for name in names
        for variant in (name, quote(name, safe=""), quote_plus(name, safe=""), html.escape(name))
    }
    for name in sorted(variants, key=len, reverse=True):
        masked = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", "[buyer]", masked, flags=re.I)
    return masked


@dataclass(frozen=True)
class IdentificationInput:
    """The answer stays outside the exact payload sent to the judge."""

    payload: str
    seed: int
    expected_choice: int
    candidate_order: tuple[str, ...]


def identify_input(case: Case, seed: int) -> IdentificationInput:
    """Shuffle choices reproducibly and retain an external scoring key.

    Args:
        case: Frozen page and all candidate summaries.
        seed: Explicit seed, shared across paired before/after observations.
    Returns:
        Exact judge payload plus separate answer and permutation metadata.
    """
    candidates = list(case.candidates)
    Random(seed).shuffle(candidates)
    names = tuple(candidate.name for candidate in candidates)
    payload = json.dumps(
        {
            "target": case.target,
            "page": mask_page(case.page, list(names)),
            "candidates": [
                {"choice": i, **candidate.model_dump()} for i, candidate in enumerate(candidates, 1)
            ],
        },
        sort_keys=True,
    )
    return IdentificationInput(payload, seed, names.index(case.buyer) + 1, names)
