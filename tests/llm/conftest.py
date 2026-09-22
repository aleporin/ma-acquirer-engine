"""Isolate token-accounting contracts from the selected production model.

Owns: Fixed arithmetic inputs for accounting and admission tests.
Does not own: Provider pricing verification or model selection.
"""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from acquirer_engine.deps import Deps
from acquirer_engine.settings import ModelSpec, PriceTier, Settings


@pytest.fixture
def accounting_model(settings: Settings) -> ModelSpec:
    """Use a fixed price table so model changes do not alter arithmetic tests."""
    path = Path(__file__).parents[1] / "fixtures" / "accounting_prices.yaml"
    tier = PriceTier.model_validate(yaml.safe_load(path.read_text()))
    return settings.models.roles["analyst"].model_copy(update={"pricing": [tier]})


@pytest.fixture
def accounting_deps(deps: Deps, accounting_model: ModelSpec) -> Deps:
    """Inject the accounting price table through the ordinary settings boundary."""
    roles = {**deps.settings.models.roles, "analyst": accounting_model}
    models = deps.settings.models.model_copy(update={"roles": roles})
    return replace(deps, settings=deps.settings.model_copy(update={"models": models}))
