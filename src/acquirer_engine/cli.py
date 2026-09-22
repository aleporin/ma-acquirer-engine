"""Register the public command surface without constructing provider clients.

Owns: Command names and process entry.
Does not own: Run composition, ranking, rendering, or evaluation.
"""

import os

import typer

from acquirer_engine.feedback.command import flag_buyer
from acquirer_engine.inspect_commands import eval_diff, show_runs
from acquirer_engine.run_command import replay_product, run_product
from evals.command import run_evaluation
from evals.judges.command import eval_judges, prepare_judges


def build_app() -> typer.Typer:
    """Build an isolated CLI without module-level application state.

    Returns:
        Registered evaluation and placeholder commands.
    """
    app = typer.Typer(help="Dataset-grounded acquirer analysis.", add_completion=False)
    app.command("eval")(run_evaluation)
    app.command("eval-diff")(eval_diff)
    app.command("eval-judges")(eval_judges)
    app.command("prepare-judges")(prepare_judges)
    app.command("run")(run_product)
    app.command("replay")(replay_product)
    app.command("runs")(show_runs)
    app.command("flag")(flag_buyer)
    return app


def main() -> None:
    """Dispatch the installed command with machine-readable diagnostics."""
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    build_app()()


if __name__ == "__main__":
    main()
