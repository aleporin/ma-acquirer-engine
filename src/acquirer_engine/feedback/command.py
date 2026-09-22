"""Expose explicit buyer exclusions through the command line.

Owns: User input and a project-local feedback update.
Does not own: Recommendation execution or network access.
"""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from acquirer_engine.data import load_transactions
from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.feedback.state import save_flag


def flag_buyer(
    acquirer: str,
    reason: Annotated[str, typer.Option(help="Why this buyer should be excluded.")],
    project: Annotated[Path, typer.Option(help="Repository root.")] = Path("."),
) -> None:
    """Save a buyer exclusion for future target rankings.

    Args:
        acquirer: Exact dataset name, matched without case sensitivity.
        reason: Nonempty explanation retained locally.
        project: Repository containing the source data and state directory.
    Raises:
        typer.Exit: Input or saved state is invalid.
    """
    try:
        root = project.resolve()
        rows = load_transactions(root / "data/ma_transactions_500.csv")
        state = save_flag(
            root / "state/feedback.json",
            acquirer,
            reason,
            {row.acquirer for row in rows if row.outcome != "Rumored"},
        )
        typer.echo(f"Saved {len(state.flags)} exclusion(s) to {root / 'state/feedback.json'}")
    except (AcquirerEngineError, OSError, ValidationError) as error:
        typer.echo(f"Feedback failed: {error}", err=True)
        raise typer.Exit(1) from error
