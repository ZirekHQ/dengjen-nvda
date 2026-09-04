"""
Tests for _config.py — the thin mapping over NVDA's config section for this
synth, which stores per-voice variant/speaker/scale settings.
"""

import os

import config
import pytest

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

_config = load_module_from_path(
    "dengjen_neural_voices._config_under_test",
    os.path.join(SYNTH_PKG_DIR, "_config.py"),
    package="dengjen_neural_voices",
)

SECTION = "dengjen_neural_voices"


@pytest.fixture
def manager():
    config.conf["speech"][SECTION].clear()
    return _config.DengjenConfigManager()


class TestModuleLevelSingleton:
    def test_exposes_a_ready_made_manager(self):
        assert isinstance(_config.DengjenConfig, _config.DengjenConfigManager)

    def test_config_spec_declares_the_voice_and_lang_sections(self):
        assert "[voices]" in _config._configSpec
        assert "[lang]" in _config._configSpec

    def test_config_spec_bounds_the_scale_settings(self):
        for setting in ("noise_scale", "length_scale", "noise_w"):
            assert f"{setting} = integer(default=50, min=0, max=100)" in (
                _config._configSpec
            )


class TestMappingProtocol:
    def test_missing_key_is_not_contained(self, manager):
        assert "de_DE-thorsten-high" not in manager

    def test_set_then_contains(self, manager):
        manager["de_DE-thorsten-high"] = {"variant": "standard"}
        assert "de_DE-thorsten-high" in manager

    def test_set_then_get_round_trips(self, manager):
        manager["en_US-amy-low"] = {"speaker": "amy"}
        assert manager["en_US-amy-low"] == {"speaker": "amy"}

    def test_writes_land_in_the_nvda_speech_section(self, manager):
        manager["en_US-amy-low"] = {"speaker": "amy"}
        assert config.conf["speech"][SECTION]["en_US-amy-low"] == {"speaker": "amy"}


class TestSetdefault:
    def test_returns_the_supplied_value_when_absent(self, manager):
        assert manager.setdefault("new-voice", {"variant": "fast"}) == {
            "variant": "fast"
        }

    def test_stores_the_supplied_value_when_absent(self, manager):
        manager.setdefault("new-voice", {"variant": "fast"})
        assert manager["new-voice"] == {"variant": "fast"}

    def test_keeps_the_existing_value_when_present(self, manager):
        manager["existing"] = {"variant": "standard"}
        assert manager.setdefault("existing", {"variant": "fast"}) == {
            "variant": "standard"
        }

    def test_does_not_overwrite_an_existing_value(self, manager):
        manager["existing"] = {"variant": "standard"}
        manager.setdefault("existing", {"variant": "fast"})
        assert manager["existing"] == {"variant": "standard"}
