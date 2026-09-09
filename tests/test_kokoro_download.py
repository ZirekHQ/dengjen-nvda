"""
Tests for kokoro_download.py: generates the exact config.json dengjen-tts's
kokoro::config::load_config expects, and drives the download/install via the
existing BaseVoiceDownloader machinery. Network is never exercised here --
_do_download_file/stream_to_file are exercised by voice_download.py's own
tests already; these tests cover kokoro_download.py's own logic only.
"""

import json
import os

import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

kokoro_download = load_module_from_path(
    "dengjen_tts_global_plugin._kokoro_download_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "kokoro_download.py"),
    package="dengjen_tts_global_plugin",
)

build_kokoro_config = kokoro_download.build_kokoro_config
KOKORO_PRESET_NAMES = kokoro_download.KOKORO_PRESET_NAMES
KokoroVoiceDownloader = kokoro_download.KokoroVoiceDownloader
KokoroCatalog = kokoro_download.KokoroCatalog


class TestBuildKokoroConfig:
    def test_matches_the_engine_schema_exactly(self):
        config = build_kokoro_config(["af_heart", "am_adam"])

        assert config == {
            "model_type": "kokoro",
            "model_path": "model.onnx",
            "voices_dir": "voices",
            "vocab_path": "tokenizer.json",
            "sample_rate": 24000,
            "voices": ["af_heart", "am_adam"],
        }

    def test_preset_list_has_fifty_four_unique_names(self):
        assert len(KOKORO_PRESET_NAMES) == 54
        assert len(set(KOKORO_PRESET_NAMES)) == 54
        assert "af_heart" in KOKORO_PRESET_NAMES
        assert "zm_yunyang" in KOKORO_PRESET_NAMES


class TestKokoroVoiceDownloaderInstall:
    def _write_temp(self, tmp_path, name, data):
        path = tmp_path / "downloaded" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_install_writes_config_and_sidecar_and_all_downloaded_files(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(kokoro_download, "DENGJEN_KOKORO_VOICES_DIR", str(tmp_path))
        downloader = KokoroVoiceDownloader(success_callback=lambda: None)
        model_bytes = b"\x00" * 16
        vocab_bytes = b'{"model": {"vocab": {"$": 0}}}'
        voice_bytes = {
            name: bytes([i % 256]) * 4 for i, name in enumerate(KOKORO_PRESET_NAMES)
        }
        # _install now takes file paths (streamed to disk by _download_work),
        # not in-memory bytes -- write the fake downloads to a temp dir first.
        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", model_bytes),
            "tokenizer.json": self._write_temp(tmp_path, "tokenizer.json", vocab_bytes),
            **{
                f"voices/{name}.bin": self._write_temp(
                    tmp_path, f"voices/{name}.bin", data
                )
                for name, data in voice_bytes.items()
            },
        }

        downloader._install(result)

        install_dir = tmp_path / "kokoro-multilingual"
        assert (install_dir / "model.onnx").read_bytes() == model_bytes
        assert (install_dir / "tokenizer.json").read_bytes() == vocab_bytes
        for name, data in voice_bytes.items():
            assert (install_dir / "voices" / f"{name}.bin").read_bytes() == data
        config = json.loads((install_dir / "config.json").read_text())
        assert config["voices"] == KOKORO_PRESET_NAMES
        sidecar = json.loads((install_dir / "voice.json").read_text())
        assert sidecar["model_type"] == "kokoro"

    def test_config_json_is_written_last_so_a_metadata_failure_leaves_nothing_installed(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(kokoro_download, "DENGJEN_KOKORO_VOICES_DIR", str(tmp_path))
        monkeypatch.setattr(
            kokoro_download.voice_metadata,
            "write",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        downloader = KokoroVoiceDownloader(success_callback=lambda: None)
        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", b"\x00"),
            "tokenizer.json": self._write_temp(tmp_path, "tokenizer.json", b"{}"),
            **{
                f"voices/{name}.bin": self._write_temp(
                    tmp_path, f"voices/{name}.bin", b""
                )
                for name in KOKORO_PRESET_NAMES
            },
        }

        with pytest.raises(kokoro_download.VoiceInstallError):
            downloader._install(result)

        install_dir = tmp_path / "kokoro-multilingual"
        assert not (install_dir / "config.json").exists()


class TestKokoroCatalog:
    def test_model_type_is_kokoro(self):
        assert KokoroCatalog().model_type == "kokoro"

    def test_is_installed_false_when_directory_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            kokoro_download, "DENGJEN_KOKORO_VOICES_DIR", str(tmp_path / "absent")
        )
        assert KokoroCatalog().is_installed() is False

    def test_is_installed_true_once_config_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kokoro_download, "DENGJEN_KOKORO_VOICES_DIR", str(tmp_path))
        install_dir = tmp_path / "kokoro-multilingual"
        install_dir.mkdir()
        (install_dir / "config.json").write_text("{}")
        assert KokoroCatalog().is_installed() is True
