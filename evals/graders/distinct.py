"""Distinctiveness evaluation placeholder.

Owns: The unimplemented result for this evaluation layer.
Does not own: Metric computation or external calls in Phase 0.
"""

from acquirer_engine.settings import LayerSpec
from evals.scorecard import LayerResult


def grade(layer: LayerSpec) -> LayerResult:
    """Report that this layer has no implementation yet.

    Args:
        layer: Configured layer identity.
    Returns:
        An explicit stub result without numeric measurements.
    """
    return LayerResult(id=layer.id, name=layer.name, selected=True, status="not_implemented")
