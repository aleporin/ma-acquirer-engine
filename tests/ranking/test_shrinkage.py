"""Test the small-sample estimator with numeric properties.

Owns: Shrinkage limits, monotonicity, and invalid arguments.
Does not own: Fitting the empirical type prior.
"""

import pytest
from acquirer_engine.ranking.shrinkage import shrink
from hypothesis import given
from hypothesis import strategies as st


def test_single_observation_is_pulled_toward_type_prior() -> None:
    assert shrink(1, 1, 0.2, 3) == pytest.approx(0.4)
    assert shrink(1, 20, 0.2, 3) > shrink(1, 1, 0.2, 3)
    assert shrink(1, 0, 0.2, 3) == 0.2


@given(st.floats(0, 1), st.floats(0, 1), st.integers(0, 500))
def test_shrinkage_is_bounded_between_observation_and_prior(
    observed: float, prior: float, count: int
) -> None:
    result = shrink(observed, count, prior, 3)
    assert min(observed, prior) - 1e-12 <= result <= max(observed, prior) + 1e-12


@given(st.floats(0, 1), st.floats(0, 1), st.integers(1, 500))
def test_increasing_observation_cannot_lower_posterior(a: float, b: float, count: int) -> None:
    low, high = sorted((a, b))
    assert shrink(low, count, 0.4, 3) <= shrink(high, count, 0.4, 3)


@pytest.mark.parametrize(("count", "strength"), [(-1, 3), (2, 0)])
def test_invalid_shrinkage_arguments_fail(count: int, strength: float) -> None:
    with pytest.raises(ValueError):
        shrink(0.5, count, 0.5, strength)
