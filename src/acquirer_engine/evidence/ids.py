"""Assign unambiguous identifiers to computed facts.

Owns: Stable stat IDs; row evidence retains the source transaction_id.
Does not own: Statistics computation or run identity.
"""

from urllib.parse import quote

from acquirer_engine.errors import EvidenceError


def stat_id(name: str, scope: str) -> str:
    """Encode a metric and scope without separator collisions.

    Args:
        name: Computed metric name.
        scope: Buyer, target, or query scope within the evidence snapshot.
    Returns:
        A stable stat:<name>:<scope> identifier with escaped components.
    Raises:
        EvidenceError: Either component is empty.
    """
    if not name.strip() or not scope.strip():
        raise EvidenceError("Statistic name and scope must be nonempty")
    return f"stat:{quote(name, safe='')}:{quote(scope, safe='')}"
