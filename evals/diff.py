"""Compare scorecards without treating missing measurements as zero.

Owns: Direction-aware metric deltas and status regression reporting.
Does not own: Running graders or claiming causal improvements.
"""

from dataclasses import dataclass

from acquirer_engine.errors import EvaluationError
from evals.scorecard import LayerResult, Scorecard


@dataclass(frozen=True)
class DiffReport:
    """Display lines and the subset that describes regressions."""

    lines: tuple[str, ...]
    regressions: tuple[str, ...]


def _metrics(before: LayerResult, after: LayerResult) -> DiffReport:
    lines, regressions = [], []
    for name in sorted(before.metrics.keys() | after.metrics.keys()):
        label = f"Layer {before.id} {name}"
        old, new = before.metrics.get(name), after.metrics.get(name)
        if old is None and new is not None:
            lines.append(f"{label}: added ({new.value:g})")
            continue
        if new is None:
            issue = f"{label}: removed"
            lines.append(issue)
            regressions.append(issue)
            continue
        assert old is not None
        if old.direction != new.direction:
            raise EvaluationError(f"{label}: metric direction changed")
        delta = new.value - old.value
        line = f"{label}: {old.value:g} -> {new.value:g}; delta {delta:+g}"
        lines.append(line)
        if (new.direction == "higher" and delta < 0) or (new.direction == "lower" and delta > 0):
            regressions.append(line)
    return DiffReport(tuple(lines), tuple(regressions))


def compare_scorecards(before: Scorecard, after: Scorecard) -> DiffReport:
    """Compare shared identities and report lost coverage or lower quality.

    Args:
        before: Earlier validated scorecard.
        after: Later validated scorecard.
    Returns:
        Descriptive changes and explicit regressions.
    Raises:
        EvaluationError: A metric's meaning changed between scorecards.
    """
    lines, regressions = [], []
    if before.config_sha256 != after.config_sha256:
        lines.append("Configuration changed; deltas are descriptive, not causal.")
    previous = {layer.id: layer for layer in before.layers}
    for current in sorted(after.layers, key=lambda layer: layer.id):
        old = previous[current.id]
        if old.name != current.name:
            raise EvaluationError(f"Layer {current.id}: identity changed")
        if old.status != current.status:
            line = f"Layer {current.id}: {old.status} -> {current.status}"
            lines.append(line)
            if old.status == "passed" or current.status == "failed":
                regressions.append(line)
        if old.selected and not current.selected:
            issue = f"Layer {current.id}: no longer selected"
            lines.append(issue)
            regressions.append(issue)
        metrics = _metrics(old, current)
        lines.extend(metrics.lines)
        regressions.extend(metrics.regressions)
    if not any(layer.metrics for layer in before.layers + after.layers):
        lines.append("No measured metrics to compare.")
    if not regressions:
        lines.append("No regressions detected.")
    return DiffReport(tuple(lines), tuple(regressions))
