"""Orchestrate offline evaluation layers.

Owns: Layer selection, injected grading, and scorecard assembly.
Does not own: Provider calls, product execution, or artifact writing.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from acquirer_engine.deps import Deps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import LayerSpec
from evals.graders import backtest, distinct, grounded, ops, rubric, stability, unit
from evals.scorecard import LayerResult, RunInfo, Scorecard

type Grader = Callable[[LayerSpec], LayerResult]


@dataclass(frozen=True)
class PreparedEvaluation:
    """Grader functions and serialized companion artifacts for one run."""

    graders: dict[int, Grader]
    artifacts: dict[str, str]


def _graders() -> dict[int, Grader]:
    return {
        0: unit.grade,
        1: backtest.grade,
        2: grounded.grade,
        3: distinct.grade,
        4: rubric.grade,
        5: stability.grade,
        6: ops.grade,
    }


def evaluate(
    deps: Deps,
    run: RunInfo,
    selected_layers: list[int],
    *,
    graders: dict[int, Grader] | None = None,
) -> Scorecard:
    """Run only offline graders and preserve the complete layer inventory.

    Args:
        deps: Shared settings and run logger.
        run: Source and invocation identity.
        selected_layers: Unique offline layer IDs.
        graders: Optional injected replacements for selected graders.
    Returns:
        A scorecard with explicit unimplemented results.
    Raises:
        EvaluationError: The layer selection is not an offline subset.
    """
    config = deps.settings.evaluation
    if not selected_layers or len(selected_layers) != len(set(selected_layers)):
        raise EvaluationError("Invalid layer selection")
    if not set(selected_layers) <= set(config.offline_layers):
        raise EvaluationError("Invalid offline layer selection")
    registered = _graders() | (graders or {})
    results = []
    for layer in sorted(config.layers, key=lambda item: item.id):
        result = LayerResult(id=layer.id, name=layer.name, selected=False, status="not_implemented")
        if layer.id in selected_layers:
            result = registered[layer.id](layer)
        results.append(result)
        deps.logger.info("layer_evaluated", stage="eval", layer=layer.id, status=result.status)
    encoded = json.dumps(deps.settings.model_dump(mode="json"), sort_keys=True).encode()
    return Scorecard(
        phase=config.phase,
        mode="replay",
        run=run,
        seed=config.seed,
        prompt_version=config.prompt_version,
        models=deps.settings.models,
        config_sha256=hashlib.sha256(encoded).hexdigest(),
        requested_layers=selected_layers,
        layers=results,
    )
