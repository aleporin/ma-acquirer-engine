"""Define the ordered rationale contract and configured section limits.

Owns: Boundary shape, enums, risk provenance, and section-size validation.
Does not own: Evidence lookup, conviction computation, or rendering.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationInfo, model_validator

from acquirer_engine.evidence.config import ValidationConfig
from acquirer_engine.ranking.conviction import Conviction

type Text = Annotated[str, Field(min_length=1)]
type RiskCategory = Literal[
    "antitrust",
    "integration_complexity",
    "financing_capacity",
    "competitive_process",
    "execution_risk",
    "portfolio_conflict",
    "fund_cycle",
]


class Boundary(BaseModel):
    """Reject unexpected fields and empty or nonfinite values."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Claim(Boundary):
    """A value in the metric's canonical units, linked to a known fact."""

    value: FiniteFloat
    metric: Text
    evidence_id: Text


class Precedent(Boundary):
    """A named transaction and its significance to the buyer thesis."""

    transaction_id: Text
    description: Text


class Comparable(Boundary):
    """A retrieved closed transaction used for valuation."""

    evidence_id: Text


class ValuationContext(Boundary):
    """A valuation narrative with explicit comparable transaction references."""

    summary: Text
    comps: Annotated[tuple[Comparable, ...], Field(min_length=1)]


class RiskFlag(Boundary):
    """A risk marked as evidence-backed or explicitly judgmental."""

    category: RiskCategory
    description: Text
    basis: Literal["evidence", "judgment"] = Field(
        description="Use evidence for an observed fact with references; judgment for an inference."
    )
    evidence_ids: tuple[Text, ...] = Field(
        description="For basis=evidence, supply known IDs. For basis=judgment, this MUST be []."
    )

    @model_validator(mode="after")
    def validate_basis(self) -> Self:
        """Require evidence or judgment, without silently mixing their meaning."""
        if bool(self.evidence_ids) != (self.basis == "evidence"):
            raise ValueError("risk requires evidence or judgment with matching references")
        return self


class ConvictionRationale(Boundary):
    """Code-selected conviction and its narrative explanation."""

    level: Conviction
    justification: Text


class AcquirerRationale(Boundary):
    """Reasoning precedes visible sections; outside notes are explicitly separate."""

    reasoning: Text
    acquirer_overview: Text
    strategic_fit_thesis: Text
    precedent_activity: Annotated[tuple[Precedent, ...], Field(min_length=1)]
    valuation_context: ValuationContext
    risk_flags: Annotated[tuple[RiskFlag, ...], Field(min_length=2)]
    conviction: ConvictionRationale
    outside_dataset_notes: Text | None = None
    claims: Annotated[tuple[Claim, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_limits(self, info: ValidationInfo) -> Self:
        """Enforce YAML caps when parsed with the required validation policy.

        Args:
            info: Validation context containing a ValidationConfig.
        Returns:
            The bounded rationale.
        Raises:
            ValueError: Configuration is absent or a section exceeds its cap.
        """
        config = info.context
        if not isinstance(config, ValidationConfig):
            raise ValueError("Rationale validation policy is required")
        errors = _length_errors(self, config)
        if errors:
            raise ValueError("; ".join(errors))
        return self


def prose_sections(page: AcquirerRationale) -> dict[str, str]:
    """Enumerate checked prose while excluding labeled outside information.

    Args:
        page: Parsed rationale.
    Returns:
        Field paths mapped to prose, including internal reasoning.
    """
    return {
        "reasoning": page.reasoning,
        "acquirer_overview": page.acquirer_overview,
        "strategic_fit_thesis": page.strategic_fit_thesis,
        "valuation_context": page.valuation_context.summary,
        "conviction.justification": page.conviction.justification,
        **{
            f"precedent_activity.{i}": item.description
            for i, item in enumerate(page.precedent_activity)
        },
        **{f"risk_flags.{i}": item.description for i, item in enumerate(page.risk_flags)},
    }


def _length_errors(page: AcquirerRationale, config: ValidationConfig) -> list[str]:
    caps = {
        "reasoning": config.reasoning_chars,
        "acquirer_overview": config.section_chars,
        "strategic_fit_thesis": config.section_chars,
        "valuation_context": config.section_chars,
    }
    lengths = {
        path: (len(text), caps.get(path, config.item_chars))
        for path, text in prose_sections(page).items()
    }
    lengths.update(
        {
            "outside_dataset_notes": (
                len(page.outside_dataset_notes or ""),
                config.outside_notes_chars,
            ),
            "precedent_activity": (len(page.precedent_activity), config.max_precedents),
            "valuation_context.comps": (len(page.valuation_context.comps), config.max_comps),
            "risk_flags": (len(page.risk_flags), config.max_risks),
            "claims": (len(page.claims), config.max_claims),
        }
    )
    return [
        f"{name} exceeds length cap {cap}" for name, (size, cap) in lengths.items() if size > cap
    ]
