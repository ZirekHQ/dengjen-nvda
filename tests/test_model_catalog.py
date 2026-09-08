"""
Tests for model_catalog.py: the ModelCatalog protocol two model backends
(Piper, Kokoro) implement so voice_manager.py can check install state
generically instead of hardcoding Piper's shape.
"""

import os

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

model_catalog = load_module_from_path(
    "dengjen_tts_global_plugin._model_catalog_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "model_catalog.py"),
    package="dengjen_tts_global_plugin",
)

PiperCatalog = model_catalog.PiperCatalog


class TestPiperCatalog:
    def test_model_type_is_piper(self):
        assert PiperCatalog().model_type == "piper"

    def test_is_installed_true_when_a_piper_voice_directory_exists(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "en-john-medium").mkdir()
        monkeypatch.setattr(model_catalog, "DENGJEN_VOICES_DIR", str(tmp_path))

        assert PiperCatalog().is_installed() is True

    def test_is_installed_false_for_empty_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(model_catalog, "DENGJEN_VOICES_DIR", str(tmp_path))

        assert PiperCatalog().is_installed() is False
