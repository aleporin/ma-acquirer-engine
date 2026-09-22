"""Create small offline CLI projects from hand-built transactions.

Owns: Fixture files required by public product commands.
Does not own: Source dataset sampling or provider credentials.
"""

import csv
from pathlib import Path
from shutil import copytree

from acquirer_engine.data.schema import Transaction


def write_project(root: Path, rows: tuple[Transaction, ...]) -> None:
    """Copy policy and prompts, then write a tiny synthetic input CSV."""
    source = Path(__file__).resolve().parents[2]
    for name in ("config", "prompts"):
        copytree(source / name, root / name)
    (root / "data").mkdir()
    values = [row.model_dump() | {"sub_sector": row.sector} for row in rows]
    with (root / "data/ma_transactions_500.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(values[0]))
        writer.writeheader()
        writer.writerows(values)
