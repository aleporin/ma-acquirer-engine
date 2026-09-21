"""Regularize noisy buyer signals toward an empirical type prior.

Owns: The convex posterior estimator.
Does not own: Prior fitting or choosing the regularization strength.
"""


def shrink(observed: float, count: int, prior: float, strength: float) -> float:
    """Blend an observed signal with a prior using pseudo-observations.

    Args:
        observed: Mean signal in the unit interval.
        count: Number of supporting observations.
        prior: Empirical mean for this buyer type.
        strength: Prior pseudo-observation count.
    Returns:
        Posterior mean between the observation and prior.
    Raises:
        ValueError: Counts, strength, or bounded inputs are invalid.
    """
    if count < 0 or strength <= 0 or not 0 <= observed <= 1 or not 0 <= prior <= 1:
        raise ValueError("Invalid shrinkage arguments")
    if count == 0:
        return prior
    return (observed * count + prior * strength) / (count + strength)
