"""Load typed transactions and describe their data quality.

Owns: Source-row contracts, CSV loading, identity checks, and discrepancy counts.
Does not own: Imputation, scoring policy, or evidence selection.
"""

import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self

import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)

from acquirer_engine.errors import DataError

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


def _validate_rows(frame: pd.DataFrame) -> tuple[Transaction, ...]:
    rows = []
    for index, record in enumerate(frame.to_dict(orient="records"), start=1):
        values = {str(key): value for key, value in record.items()}
        if values.pop("sub_sector") != values["sector"]:
            raise DataError(f"Redundant sector mismatch in row {index}")
        try:
            rows.append(Transaction.model_validate(values))
        except ValidationError as error:
            fields = sorted({str(item["loc"][0]) for item in error.errors() if item["loc"]})
            raise DataError(f"Invalid CSV row {index}; fields: {', '.join(fields)}") from None
    return tuple(rows)


def _check_identity(rows: tuple[Transaction, ...]) -> None:
    ids = [row.transaction_id for row in rows]
    if len(ids) != len(set(ids)):
        raise DataError("Duplicate transaction identity")
    types: dict[str, str] = {}
    for row in rows:
        if row.acquirer in types and types[row.acquirer] != row.acquirer_type:
            raise DataError("Conflicting acquirer types")
        types[row.acquirer] = row.acquirer_type


def load_transactions(path: Path) -> tuple[Transaction, ...]:
    """Read validated rows without imputing values or changing stated multiples.

    Args:
        path: CSV file with the required transaction fields.
    Returns:
        Immutable typed rows sorted by transaction identity.
    Raises:
        DataError: The file, schema, or dataset identities are invalid.
    """
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise DataError(f"Could not read transaction CSV: {path.name}") from error
    expected = set(Transaction.model_fields) | {"sub_sector"}
    if set(frame.columns) != expected or frame.empty:
        raise DataError("CSV columns must match the transaction schema and contain rows")
    rows = _validate_rows(frame)
    _check_identity(rows)
    return tuple(sorted(rows, key=lambda row: row.transaction_id))


class QualityReport(BaseModel):
    """Counts of observed inconsistencies and expected missingness."""

    model_config = ConfigDict(frozen=True)
    rows: int
    acquirers: int
    multiple_mismatches: int
    margin_mismatches: int
    sponsor_deal_type_conflicts: int
    strategic_deal_type_conflicts: int
    rumored: int
    null_days_to_close: int


def quality_report(
    rows: Sequence[Transaction], *, multiple_tolerance: float, margin_tolerance: float
) -> QualityReport:
    """Measure discrepancies against canonical stated values.

    Args:
        rows: Validated transactions.
        multiple_tolerance: Relative difference allowed against the stated multiple.
        margin_tolerance: Absolute percentage-point margin difference allowed.
    Returns:
        Aggregate counts with no raw transaction values.
    """
    return QualityReport(
        rows=len(rows),
        acquirers=len({row.acquirer for row in rows}),
        multiple_mismatches=sum(
            abs(row.deal_size_mm / row.target_ebitda_mm - row.ev_ebitda_multiple)
            / row.ev_ebitda_multiple
            > multiple_tolerance
            for row in rows
        ),
        margin_mismatches=sum(
            abs(row.target_ebitda_mm / row.target_revenue_mm * 100 - row.ebitda_margin_pct)
            > margin_tolerance
            for row in rows
        ),
        sponsor_deal_type_conflicts=sum(
            row.acquirer_type == "Financial Sponsor"
            and row.deal_type in {"Strategic Acquisition", "Merger of Equals"}
            for row in rows
        ),
        strategic_deal_type_conflicts=sum(
            row.acquirer_type == "Strategic"
            and row.deal_type in {"Leveraged Buyout", "Platform Investment"}
            for row in rows
        ),
        rumored=sum(row.outcome == "Rumored" for row in rows),
        null_days_to_close=sum(row.days_to_close is None for row in rows),
    )
