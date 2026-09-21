"""Load the CSV through a typed validation boundary.

Owns: CSV structure, row validation, and dataset identity checks.
Does not own: Correcting stated values or selecting scoring rows.
"""

from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import DataError


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
