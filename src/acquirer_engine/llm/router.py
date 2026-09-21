"""Choose bounded validation recovery and evidence-density routes.

Owns: Deterministic pass, repair, escalation, and banner decisions.
Does not own: Calling models, changing evidence, or overriding validation.
"""

from typing import Literal

from acquirer_engine.llm.config import AnalystConfig

type Route = Literal["pass", "repair", "escalate", "banner"]


def next_route(*, passed: bool, repairable: bool, repairs: int, config: AnalystConfig) -> Route:
    """Select the next action from a validation result and remaining attempts.

    Args:
        passed: Whether the complete page passed deterministic validation.
        repairable: Whether failure describes output the model can correct.
        repairs: Completed correction attempts, excluding the original draft.
        config: Loaded limits and escalation policy.
    Returns:
        One explicit action; every terminal failure remains unverified.
    """
    if passed:
        return "pass"
    if not repairable or repairs >= config.max_repairs:
        return "banner"
    if repairs == 0:
        return "repair"
    return "escalate" if repairs == 1 and config.escalation_enabled else "banner"
