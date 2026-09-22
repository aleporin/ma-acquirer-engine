"""Load saved runs with explicit provenance checks.

Owns: Schema, run identity, source cohort, and execution-mode consistency.
Does not own: Running providers or assigning evaluation grades.
"""

from pathlib import Path

from pydantic import ValidationError

from acquirer_engine.errors import EvaluationError
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.settings import Settings


def load_runs(paths: list[Path], settings: Settings) -> list[AnalystRun]:
    """Validate a comparable cohort without changing historical observations.

    Args:
        paths: Saved run artifacts.
        settings: Rationale validation policy.
    Returns:
        Runs sharing source and prompt versions, with unique identities.
    Raises:
        EvaluationError: A run is malformed, duplicated, or incompatible.
    """
    try:
        runs = [
            AnalystRun.model_validate_json(path.read_text(), context=settings.evidence.validation)
            for path in paths
        ]
    except (OSError, ValueError, ValidationError) as error:
        raise EvaluationError("Invalid analyst run artifact") from error
    if len({run.run_id for run in runs}) != len(runs):
        raise EvaluationError("Duplicate analyst run identity")
    if len({(run.git_sha, run.prompt_version) for run in runs}) > 1:
        raise EvaluationError("Analyst stability requires matching source and prompt versions")
    if any(call.mode != run.mode for run in runs for call in run.calls):
        raise EvaluationError("Run mode conflicts with response usage mode")
    return runs
