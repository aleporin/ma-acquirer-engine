"""Exercise configuration loading at the YAML boundary.

Owns: Valid configuration and rejection of malformed inputs.
Does not own: Model execution or scoring policy.
"""

from pathlib import Path
from shutil import copytree

import pytest
import yaml

from acquirer_engine.errors import ConfigError
from acquirer_engine.settings import load_settings


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "config"
    destination = tmp_path / "config"
    copytree(source, destination)
    return destination


def test_loads_all_configuration_without_environment(config_dir: Path) -> None:
    settings = load_settings(config_dir)
    assert settings.evaluation.phase == "p0"
    assert [layer.id for layer in settings.evaluation.layers] == list(range(7))
    assert settings.scoring.weights is None
    assert settings.models.roles
    for model in settings.models.roles.values():
        assert model.source_urls
        assert model.as_of.isoformat()
        assert model.pricing[0].input_usd_per_million > 0


def test_invalid_yaml_is_reported_without_echoing_values(config_dir: Path) -> None:
    (config_dir / "models.yaml").write_text("roles: [broken\n")
    with pytest.raises(ConfigError, match="models.yaml") as error:
        load_settings(config_dir)
    assert "broken" not in str(error.value)


def test_unsafe_yaml_constructors_are_rejected(config_dir: Path) -> None:
    (config_dir / "scoring.yaml").write_text("!!python/tuple [1, 2]\n")
    with pytest.raises(ConfigError):
        load_settings(config_dir)


def test_negative_prices_are_rejected(config_dir: Path) -> None:
    path = config_dir / "models.yaml"
    config = yaml.safe_load(path.read_text())
    first = next(iter(config["roles"].values()))
    first["pricing"][0]["input_usd_per_million"] = -1
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ConfigError, match="models.yaml"):
        load_settings(config_dir)


def test_duplicate_layer_ids_are_rejected(config_dir: Path) -> None:
    path = config_dir / "eval.yaml"
    config = yaml.safe_load(path.read_text())
    config["layers"][1]["id"] = config["layers"][0]["id"]
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ConfigError, match="eval.yaml"):
        load_settings(config_dir)


def test_unknown_fields_are_rejected(config_dir: Path) -> None:
    (config_dir / "scoring.yaml").write_text("weigths: null\n")
    with pytest.raises(ConfigError, match="scoring.yaml"):
        load_settings(config_dir)


def test_missing_config_has_a_specific_filename(config_dir: Path) -> None:
    (config_dir / "eval.yaml").unlink()
    with pytest.raises(ConfigError, match="eval.yaml"):
        load_settings(config_dir)
