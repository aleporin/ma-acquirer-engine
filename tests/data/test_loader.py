"""Exercise CSV validation and the measured source profile.

Owns: Typed rows, rejected inputs, and source-data invariants.
Does not own: Feature engineering or acquirer selection.
"""

import csv
from pathlib import Path

import pytest

from acquirer_engine.data import load_transactions
from acquirer_engine.errors import DataError


def csv_path() -> Path:
    """Locate the unchanged source dataset."""
    return Path(__file__).resolve().parents[2] / "data/ma_transactions_500.csv"


def test_source_profile_and_redundant_column_removal() -> None:
    rows = load_transactions(csv_path())
    assert len(rows) == 500
    assert len({row.acquirer for row in rows}) == 107
    assert len({row.transaction_id for row in rows}) == 500
    assert sum(row.days_to_close is None for row in rows) == 94
    assert all((row.days_to_close is None) == (row.outcome != "Closed") for row in rows)
    assert all("sub_sector" not in row.model_dump() for row in rows)
    assert sum(row.deal_year <= 2021 for row in rows) == 358


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sub_sector", "wrong"),
        ("outcome", "Unknown"),
        ("deal_size_mm", "nan"),
        ("days_to_close", ""),
        ("acquirer", ""),
        ("deal_year", "2020.5"),
    ],
)
def test_invalid_row_fails_without_echoing_source_values(
    tmp_path: Path, field: str, value: str
) -> None:
    with csv_path().open() as stream:
        rows = list(csv.DictReader(stream))
    closed = next(row for row in rows if row["outcome"] == "Closed")
    closed[field] = value
    destination = tmp_path / "bad.csv"
    with destination.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(closed))
        writer.writeheader()
        writer.writerow(closed)
    with pytest.raises(DataError) as error:
        load_transactions(destination)
    assert closed["target_company"] not in str(error.value)


def test_missing_columns_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"
    path.write_text("acquirer\nExample\n")
    with pytest.raises(DataError, match="columns"):
        load_transactions(path)


def test_duplicate_identity_is_rejected(tmp_path: Path) -> None:
    lines = csv_path().read_text().splitlines()
    path = tmp_path / "duplicate.csv"
    path.write_text("\n".join([lines[0], lines[1], lines[1]]) + "\n")
    with pytest.raises(DataError, match="Duplicate"):
        load_transactions(path)


def test_missing_file_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="read"):
        load_transactions(tmp_path / "missing.csv")
