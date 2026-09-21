"""Verify ranking policy is validated before scoring.

Owns: Configured weights, bands, and conviction boundaries.
Does not own: Fitting or holdout evaluation.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from acquirer_engine.ranking.config import RankingConfig


def policy_data() -> dict[str, object]:
    """Read the published ranking policy for boundary mutations."""
    return dict(
        yaml.safe_load((Path(__file__).resolve().parents[1] / "config/scoring.yaml").read_text())
    )


def test_weights_sum_to_one_and_bands_scale() -> None:
    config = RankingConfig.model_validate(policy_data())
    assert sum(config.weights.values()) == pytest.approx(1)
    assert config.size_band == (0.5, 2.0)
    assert config.default_target.deal_size_mm == 200


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("size_band", [2, 0.5]),
        ("weights", {"sector_fit": 1}),
        ("prior_strength", 0),
        ("high_score", 0.2),
        ("adjacent_discount", 1.1),
    ],
)
def test_invalid_ranking_policy_is_rejected(key: str, value: object) -> None:
    values = policy_data()
    values[key] = value
    with pytest.raises(ValidationError):
        RankingConfig.model_validate(values)
