"""Define validated transaction records.

Owns: CSV field types and row-level consistency.
Does not own: File loading, quality policy, or ranking.
"""

import unicodedata
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

type AcquirerType = Literal["Financial Sponsor", "Strategic"]
type Outcome = Literal["Closed", "Withdrawn", "Pending", "Terminated", "Rumored"]
type Text = Annotated[str, Field(min_length=1)]


class Transaction(BaseModel):
    """Canonical row after the redundant sub-sector column is removed."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    transaction_id: Annotated[str, Field(pattern=r"^MA-\d{4}-\d{4}$")]
    target_company: Text
    acquirer: Text
    sector: Text
    deal_year: PositiveInt
    deal_quarter: Literal["Q1", "Q2", "Q3", "Q4"]
    deal_type: Text
    geography: Text
    financing_type: Text
    deal_size_mm: PositiveFloat
    target_revenue_mm: PositiveFloat
    target_ebitda_mm: PositiveFloat
    ebitda_margin_pct: Annotated[float, Field(gt=0, le=100)]
    revenue_growth_pct: float
    ev_ebitda_multiple: PositiveFloat
    ev_revenue_multiple: PositiveFloat
    synergy_pct_of_deal: Annotated[float, Field(ge=0, le=100)]
    outcome: Outcome
    strategic_rationale_tags: Text
    num_bidders: PositiveInt
    days_to_close: PositiveInt | None
    acquirer_type: AcquirerType
    target_ownership_pre: Literal["Private", "PE-Backed", "Public", "Non-Profit"]

    @field_validator("*", mode="before")
    @classmethod
    def clean_text(cls, value: object) -> object:
        """Remove control characters at the untrusted input boundary."""
        if isinstance(value, str):
            return "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cf"}).strip()
        return value

    @field_validator("days_to_close", mode="before")
    @classmethod
    def nullable_days(cls, value: object) -> object:
        """Keep missing close time as an explicit null."""
        return None if value == "" else value

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """Reject inconsistent identity years or close times."""
        if int(self.transaction_id.split("-")[1]) != self.deal_year:
            raise ValueError("Identity year must match deal year")
        if (self.days_to_close is None) != (self.outcome != "Closed"):
            raise ValueError("Only closed transactions have days_to_close")
        return self
