"""Specify target overrides without changing the base ranking policy.

Owns: YAML precedence, measured default margins, and invalid-input rejection.
Does not own: Buyer selection or provider access.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from acquirer_engine.errors import DataError
from acquirer_engine.settings import Settings
from acquirer_engine.stages import select as module
from tests.fixtures.ranking import transaction


def test_cli_overrides_yaml_and_margin_is_measured_for_selected_sector(
    settings: Settings, tmp_path: Path
) -> None:
    path = tmp_path / "target.yaml"
    path.write_text("sector: Services\ndeal_size_mm: 100\ntags: []\n")
    rows = (transaction(1, ebitda_margin_pct=12), transaction(2, ebitda_margin_pct=24))
    target = module.resolve_target(
        rows, settings.scoring, path, module.TargetOverrides(deal_size_mm=300)
    )
    assert target.deal_size_mm == 300
    assert target.ebitda_margin_pct == pytest.approx(20)
    assert target.sector == "Services" and target.tags == ()
    assert target.size_band(settings.scoring) == (150, 600)


@pytest.mark.parametrize("content", ["unexpected: true", "deal_size_mm: -1", "[]", "sector: ' '"])
def test_invalid_target_yaml_fails_at_input_boundary(
    settings: Settings, tmp_path: Path, content: str
) -> None:
    path = tmp_path / "target.yaml"
    path.write_text(content)
    with pytest.raises((DataError, ValidationError)):
        module.resolve_target((transaction(),), settings.scoring, path, None)


def test_unobserved_sector_requires_explicit_margin(settings: Settings) -> None:
    values = module.TargetOverrides(sector="New sector")
    with pytest.raises(DataError, match="margin"):
        module.resolve_target((transaction(),), settings.scoring, None, values)
    target = module.resolve_target(
        (transaction(),),
        settings.scoring,
        None,
        values.model_copy(update={"ebitda_margin_pct": 15}),
    )
    assert target.sector == "New sector" and target.ebitda_margin_pct == 15
