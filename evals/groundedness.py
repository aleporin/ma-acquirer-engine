"""Add evidence validation measurements to the existing ranking evaluation.

Owns: Groundedness grader composition and its companion artifact.
Does not own: Replacing ranking results or running live generation.
"""

from functools import partial
from pathlib import Path

from acquirer_engine.evidence.config import ValidationConfig
from evals.graders.grounded import grade
from evals.grounded import run_fixture_suite
from evals.harness import PreparedEvaluation


def prepare_groundedness(
    prepared: PreparedEvaluation, root: Path, config: ValidationConfig
) -> PreparedEvaluation:
    """Retain earlier measurements while making layer two executable.

    Args:
        prepared: Measured ranking and unit layers.
        root: Repository containing the fixture suite.
        config: Shared rationale validation policy.
    Returns:
        Graders and artifacts with fixture outcomes added.
    """
    report = run_fixture_suite(root / "evals/fixtures/grounded", config)
    return PreparedEvaluation(
        graders=prepared.graders | {2: partial(grade, report=report)},
        artifacts=prepared.artifacts
        | {"groundedness.json": report.model_dump_json(indent=2) + "\n"},
    )
