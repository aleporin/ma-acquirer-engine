"""Validate evidence budgets and rationale validation policy.

Owns: Typed settings loaded from evidence.yaml.
Does not own: Loading files or selecting evidence.
"""

from pydantic import BaseModel, ConfigDict, NonNegativeFloat, NonNegativeInt, PositiveInt


class PackConfig(BaseModel):
    """Bound rows and conservative token capacity independently."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_rows: NonNegativeInt
    max_tokens: PositiveInt


class ValidationConfig(BaseModel):
    """Rounding and section limits, shared by schema and verifier."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    rounding_tolerance: NonNegativeFloat
    reasoning_chars: PositiveInt
    section_chars: PositiveInt
    item_chars: PositiveInt
    outside_notes_chars: PositiveInt
    max_precedents: PositiveInt
    max_comps: PositiveInt
    max_risks: PositiveInt
    max_claims: PositiveInt
    banned_phrases: tuple[str, ...]


class EvidenceConfig(BaseModel):
    """One evidence configuration snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    pack: PackConfig
    validation: ValidationConfig
