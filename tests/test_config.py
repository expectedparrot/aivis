import pytest
import yaml

from aivis.config import Config, configure_collection, default_config, load_config, save_config


def test_cache_defaults_and_round_trip(tmp_path):
    project = tmp_path / ".aivis"
    project.mkdir()
    config = default_config("Upwork", ["Fiverr"])
    assert config.collection.api_cache is False
    assert config.collection.judge_cache is True
    assert config.collection.remote is True
    save_config(project, config)
    assert load_config(project) == config


def test_unknown_keys_rejected(tmp_path):
    project = tmp_path / ".aivis"
    project.mkdir()
    (project / "aivis.yaml").write_text(yaml.safe_dump({"brand": {"name": "X"}, "surprise": 1}))
    with pytest.raises(ValueError, match="surprise"):
        load_config(project)


def test_duplicate_brands_rejected():
    with pytest.raises(ValueError, match="unique"):
        Config.model_validate({"brand": {"name": "X"}, "competitors": [{"name": "x"}]})


def test_configure_collection_is_atomic_and_validated():
    configured = configure_collection(
        default_config("Upwork", ["Fiverr"]),
        engines=["claude-sonnet-4-6"],
        samples_per_prompt=1,
    )
    assert [item.id for item in configured.engines.api if item.enabled] == [
        "claude-sonnet-4-6"
    ]
    assert configured.sampling.runs_per_prompt == 1
    assert configured.collection.remote is True
    with pytest.raises(ValueError, match="Unknown API engine"):
        configure_collection(configured, engines=["made-up"], samples_per_prompt=1)
