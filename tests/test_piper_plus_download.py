"""
Tests for piper_plus_download.py: verifies all 6 Piper-Plus languages and all
7 published Piper-Plus voice models, commit/SHA-256 pinning, config enrichment,
verified sibling-model reuse, hard-link/copy installation, multi-language
failure rollback, and hosting overrides.
"""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

piper_plus_download = load_module_from_path(
    "dengjen_tts_global_plugin._piper_plus_download_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "piper_plus_download.py"),
    package="dengjen_tts_global_plugin",
)

PIPER_PLUS_LANGUAGES = piper_plus_download.PIPER_PLUS_LANGUAGES
PIPER_PLUS_MODELS = piper_plus_download.PIPER_PLUS_MODELS
PiperPlusVoiceDownloader = piper_plus_download.PiperPlusVoiceDownloader
build_piper_plus_config = piper_plus_download.build_piper_plus_config
get_all_piper_plus_voices = piper_plus_download.get_all_piper_plus_voices
get_available_piper_plus_voices = piper_plus_download.get_available_piper_plus_voices


class TestPiperPlusCatalogDefinitions:
    """Verify catalog definitions, commit/checksum pins, and voice expansion."""

    def test_covers_all_six_piper_plus_languages(self):
        codes = [lang.code for lang in PIPER_PLUS_LANGUAGES]
        assert codes == ["ja_JP", "en_US", "zh_CN", "es_ES", "fr_FR", "pt_BR"]

    def test_covers_all_seven_piper_plus_models_with_commit_and_sha256_pins(self):
        model_ids = [m.model_id for m in PIPER_PLUS_MODELS]
        assert model_ids == [
            "tsukuyomi_chan",
            "tsukuyomi_zs",
            "css10_ja_6lang",
            "mera_multilingual",
            "piper_plus_base",
            "css10_ja",
            "piper_ljspeech",
        ]
        for spec in PIPER_PLUS_MODELS:
            assert re.fullmatch(r"[0-9a-f]{40}", spec.commit)
            assert re.fullmatch(r"[0-9a-f]{64}", spec.onnx_sha256)
            assert re.fullmatch(r"[0-9a-f]{64}", spec.config_sha256)

    def test_expands_thirty_two_language_voice_entries(self, tmp_path):
        voices = get_all_piper_plus_voices(tmp_path)
        assert len(voices) == 32
        keys = {v.key for v in voices}
        assert "ja_JP-tsukuyomi_chan-medium" in keys
        assert "en_US-tsukuyomi_chan-medium" in keys
        assert "zh_CN-tsukuyomi_chan-medium" in keys
        assert "es_ES-tsukuyomi_chan-medium" in keys
        assert "fr_FR-tsukuyomi_chan-medium" in keys
        assert "pt_BR-tsukuyomi_chan-medium" in keys
        assert "ja_JP-css10_ja-medium" in keys
        assert "en_US-piper_ljspeech-medium" in keys

    def test_available_voices_excludes_already_installed_entries(self, tmp_path):
        installed_dir = tmp_path / "ja_JP-tsukuyomi_chan-medium"
        installed_dir.mkdir(parents=True)
        (installed_dir / "ja_JP-tsukuyomi_chan-medium.onnx").write_bytes(b"model")
        (installed_dir / "ja_JP-tsukuyomi_chan-medium.onnx.json").write_text("{}")

        missing_onnx_dir = tmp_path / "en_US-tsukuyomi_chan-medium"
        missing_onnx_dir.mkdir(parents=True)
        (missing_onnx_dir / "en_US-tsukuyomi_chan-medium.onnx.json").write_text("{}")

        available = get_available_piper_plus_voices(tmp_path)
        available_keys = {v.key for v in available}
        assert "ja_JP-tsukuyomi_chan-medium" not in available_keys
        assert "en_US-tsukuyomi_chan-medium" in available_keys
        assert len(available) == 31


class TestBuildPiperPlusConfig:
    """Verify per-language metadata stamping in generated config JSON."""

    def test_stamps_language_and_piper_plus_metadata(self, tmp_path):
        voice = next(
            v
            for v in get_all_piper_plus_voices(tmp_path)
            if v.key == "ja_JP-tsukuyomi_chan-medium"
        )
        raw = {"audio": {"sample_rate": 22050}, "phoneme_type": "multilingual"}
        enriched = build_piper_plus_config(raw, voice)

        assert enriched["dataset"] == "tsukuyomi_chan"
        assert enriched["language"]["code"] == "ja_JP"
        assert enriched["language"]["family"] == "ja"
        assert enriched["piper_plus"] == {
            "repo_id": "ayousanz/piper-plus-tsukuyomi-chan",
            "commit": voice.spec.commit,
            "model_id": "tsukuyomi_chan",
            "phoneme_type": "multilingual",
            "language_code": "ja_JP",
            "language_family": "ja",
            "language_id": 0,
        }

    def test_omits_language_id_for_single_language_models(self, tmp_path):
        """Ensure single-language models without language embeddings omit language_id."""
        voices = {v.key: v for v in get_all_piper_plus_voices(tmp_path)}
        for key in ("ja_JP-css10_ja-medium", "en_US-piper_ljspeech-medium"):
            voice = voices[key]
            assert voice.language_id is None
            enriched = build_piper_plus_config({}, voice)
            assert "language_id" not in enriched["piper_plus"]


class TestDownloadToFileAndCaching:
    """Verify URL pinning, size/SHA-256 checks, progress forwarding, and sibling reuse."""

    def _fake_follow_redirects(self, content_length, seen_urls=None):
        @contextmanager
        def follow_redirects(url, label, headers=None):
            if seen_urls is not None:
                seen_urls.append(url)
            response = MagicMock()
            response.getheader.return_value = content_length
            yield response

        return follow_redirects

    def test_raises_and_deletes_the_file_when_the_size_does_not_match(
        self, tmp_path, monkeypatch
    ):
        spec = PIPER_PLUS_MODELS[0]
        payload = b"short"
        digest = hashlib.sha256(payload).hexdigest()
        monkeypatch.setattr(
            piper_plus_download, "follow_redirects", self._fake_follow_redirects("10")
        )
        monkeypatch.setattr(
            piper_plus_download,
            "stream_to_file",
            lambda _resp, target_file, _size, _cb: Path(target_file).write_bytes(
                payload
            ),
        )
        target = tmp_path / "model.onnx"

        with pytest.raises(RuntimeError, match="size"):
            piper_plus_download._download_to_file(spec, spec.onnx_path, digest, target)

        assert not target.exists()

    def test_raises_and_deletes_the_file_when_sha256_does_not_match(
        self, tmp_path, monkeypatch
    ):
        """Ensure missing Content-Length still fails if SHA-256 does not match."""
        spec = PIPER_PLUS_MODELS[0]
        monkeypatch.setattr(
            piper_plus_download,
            "follow_redirects",
            self._fake_follow_redirects("not-a-number"),
        )
        monkeypatch.setattr(
            piper_plus_download,
            "stream_to_file",
            lambda _resp, target_file, total_size, cb: (
                assert_zero := (total_size == 0),
                cb(50),
                Path(target_file).write_bytes(b"corrupted"),
                assert_zero,
            ),
        )
        progress_seen = []
        target = tmp_path / "model.onnx"

        with pytest.raises(RuntimeError, match="SHA-256"):
            piper_plus_download._download_to_file(
                spec,
                spec.onnx_path,
                "0" * 64,
                target,
                progress_callback=progress_seen.append,
            )

        assert progress_seen == [50]
        assert not target.exists()

    def test_uses_hosting_override_and_pinned_commit_sha(
        self, tmp_path, monkeypatch, hosting_overrides
    ):
        hosting_overrides["piper_plus_download_prefix"] = "https://mirror.example/hf"
        spec = PIPER_PLUS_MODELS[0]
        payload = b'{"ok": true}'
        digest = hashlib.sha256(payload).hexdigest()
        seen = []

        monkeypatch.setattr(
            piper_plus_download,
            "follow_redirects",
            self._fake_follow_redirects(str(len(payload)), seen_urls=seen),
        )
        monkeypatch.setattr(
            piper_plus_download,
            "stream_to_file",
            lambda _resp, target_file, _size, cb: (
                cb(100),
                Path(target_file).write_bytes(payload),
            ),
        )

        piper_plus_download._download_to_file(
            spec, spec.config_path, digest, tmp_path / "cfg.json"
        )

        assert seen == [
            f"https://mirror.example/hf/{spec.repo_id}/resolve/{spec.commit}/{spec.config_path}"
        ]

    def test_find_cached_sibling_onnx_validates_sha256_and_downloads_pinned_config(
        self, tmp_path, monkeypatch
    ):
        """Ensure sibling reuse verifies `.onnx` SHA-256 and still fetches pinned config."""
        voices_root = tmp_path / "voices"
        dl_dir = tmp_path / "dl"
        dl_dir.mkdir()
        base_spec = PIPER_PLUS_MODELS[0]
        good_bytes = b"verified-onnx"
        good_sha = hashlib.sha256(good_bytes).hexdigest()
        spec = type(base_spec)(**{**base_spec.__dict__, "onnx_sha256": good_sha})

        bad_key = "ja_JP-tsukuyomi_chan-medium"
        bad_dir = voices_root / bad_key
        bad_dir.mkdir(parents=True)
        (bad_dir / f"{bad_key}.onnx").write_bytes(b"truncated")

        assert piper_plus_download._find_cached_sibling_onnx(spec, voices_root) is None

        good_key = "en_US-tsukuyomi_chan-medium"
        good_dir = voices_root / good_key
        good_dir.mkdir()
        (good_dir / f"{good_key}.onnx").write_bytes(good_bytes)
        # Even a modified sibling `.onnx.json` cannot bypass pinned config verification.
        (good_dir / f"{good_key}.onnx.json").write_text("{}")

        cached = piper_plus_download._find_cached_sibling_onnx(spec, voices_root)
        assert cached == good_dir / f"{good_key}.onnx"

        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )
        base_voice = next(
            v
            for v in get_all_piper_plus_voices(voices_root)
            if v.key == "zh_CN-tsukuyomi_chan-medium"
        )
        voice = type(base_voice)(**{**base_voice.__dict__, "spec": spec})
        downloader = PiperPlusVoiceDownloader(voice, success_callback=lambda: None)
        downloader.download_dir = str(dl_dir)
        downloader.update_progress = lambda _pct: None
        downloader._report_progress = lambda _pct, _msg: None

        downloaded_paths = []

        def _fake_download(_spec, rel_path, sha, target_path, progress_callback=None):
            downloaded_paths.append((rel_path, sha))
            progress_callback(100)
            Path(target_path).write_text('{"phoneme_type": "multilingual"}')

        monkeypatch.setattr(piper_plus_download, "_download_to_file", _fake_download)

        out = downloader._download_work()
        assert out["model.onnx"] == good_dir / f"{good_key}.onnx"
        assert out["config.json"] == dl_dir / "config.json"
        assert downloaded_paths == [(spec.config_path, spec.config_sha256)]


class TestPiperPlusVoiceDownloaderInstall:
    """Verify installation, hard-linking, copy fallback, progress, and rollback."""

    def _write_temp(self, tmp_path, name, data):
        path = tmp_path / "downloaded" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_install_single_language_writes_onnx_sidecar_and_config(
        self, tmp_path, monkeypatch
    ):
        voices_root = tmp_path / "voices"
        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )
        voice = next(
            v
            for v in get_all_piper_plus_voices(voices_root)
            if v.key == "ja_JP-tsukuyomi_chan-medium"
        )
        downloader = PiperPlusVoiceDownloader(voice, success_callback=lambda: None)
        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", b"\x00" * 16),
            "config.json": self._write_temp(
                tmp_path,
                "config.json",
                b'{"audio": {"sample_rate": 22050}, "phoneme_type": "multilingual"}',
            ),
        }

        downloader._install(result)

        install_dir = voices_root / "ja_JP-tsukuyomi_chan-medium"
        assert (
            install_dir / "ja_JP-tsukuyomi_chan-medium.onnx"
        ).read_bytes() == b"\x00" * 16
        sidecar = json.loads((install_dir / "voice.json").read_text("utf-8"))
        assert sidecar["model_type"] == "piper-plus"
        assert sidecar["language"] == "ja_JP"
        config = json.loads(
            (install_dir / "ja_JP-tsukuyomi_chan-medium.onnx.json").read_text("utf-8")
        )
        assert config["piper_plus"]["language_id"] == 0

    def test_install_all_languages_hardlinks_shared_onnx_and_falls_back_to_copy(
        self, tmp_path, monkeypatch
    ):
        """Ensure multi-language install hard-links `.onnx` and falls back cleanly."""
        voices_root = tmp_path / "voices"
        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )
        voice = next(
            v
            for v in get_all_piper_plus_voices(voices_root)
            if v.key == "ja_JP-tsukuyomi_chan-medium"
        )
        downloader = PiperPlusVoiceDownloader(
            voice, success_callback=lambda: None, install_all_languages=True
        )
        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", b"onnx-bytes"),
            "config.json": self._write_temp(
                tmp_path, "config.json", b'{"phoneme_type": "multilingual"}'
            ),
        }

        downloader._install(result)

        inodes = set()
        for lang_code in ("ja_JP", "en_US", "zh_CN", "es_ES", "fr_FR", "pt_BR"):
            key = f"{lang_code}-tsukuyomi_chan-medium"
            onnx_path = voices_root / key / f"{key}.onnx"
            assert onnx_path.read_bytes() == b"onnx-bytes"
            assert (voices_root / key / f"{key}.onnx.json").is_file()
            inodes.add(onnx_path.stat().st_ino)
        assert len(inodes) == 1

        fallback_root = tmp_path / "fallback_voices"
        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(fallback_root)
        )
        monkeypatch.setattr(
            piper_plus_download.os,
            "link",
            lambda *_args: (_ for _ in ()).throw(OSError("cross-device link")),
        )
        downloader._install(result)
        assert (
            fallback_root
            / "pt_BR-tsukuyomi_chan-medium"
            / "pt_BR-tsukuyomi_chan-medium.onnx"
        ).read_bytes() == b"onnx-bytes"

    def test_multi_language_failure_rolls_back_all_directories_from_run(
        self, tmp_path, monkeypatch
    ):
        """Ensure failing partway through all-languages cleans up newly written dirs."""
        voices_root = tmp_path / "voices"
        preexisting = voices_root / "ja_JP-tsukuyomi_chan-medium"
        preexisting.mkdir(parents=True)
        (preexisting / "ja_JP-tsukuyomi_chan-medium.onnx").write_bytes(b"kept")
        (preexisting / "voice.json").write_text('{"model_type": "piper-plus"}')
        (preexisting / "ja_JP-tsukuyomi_chan-medium.onnx.json").write_text("{}")

        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )
        real_write = piper_plus_download.voice_metadata.write
        calls = 0

        def _fail_on_third_language(install_dir, metadata):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("disk full partway through")
            real_write(install_dir, metadata)

        monkeypatch.setattr(
            piper_plus_download.voice_metadata, "write", _fail_on_third_language
        )
        voice = next(
            v
            for v in get_all_piper_plus_voices(voices_root)
            if v.key == "en_US-tsukuyomi_chan-medium"
        )
        downloader = PiperPlusVoiceDownloader(
            voice, success_callback=lambda: None, install_all_languages=True
        )
        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", b"new-bytes"),
            "config.json": self._write_temp(tmp_path, "config.json", b"{}"),
        }

        with pytest.raises(piper_plus_download.VoiceInstallError):
            downloader._install(result)

        remaining = sorted(p.name for p in voices_root.iterdir())
        assert remaining == ["ja_JP-tsukuyomi_chan-medium"]
        assert (
            preexisting / "ja_JP-tsukuyomi_chan-medium.onnx"
        ).read_bytes() == b"kept"
        assert (
            preexisting / "ja_JP-tsukuyomi_chan-medium.onnx.json"
        ).read_text() == "{}"

    def test_atomic_staging_preserves_existing_files_on_copy_or_write_failure(
        self, tmp_path, monkeypatch
    ):
        """Ensure failed copyfile or config write leaves existing destination intact."""
        src = tmp_path / "src.onnx"
        src.write_bytes(b"new-model")
        dst = tmp_path / "dst.onnx"
        dst.write_bytes(b"existing-intact-model")

        monkeypatch.setattr(
            piper_plus_download.os,
            "link",
            lambda *_args: (_ for _ in ()).throw(OSError("no hardlink")),
        )

        def _failing_copy(_src_p, dst_p):
            Path(dst_p).write_bytes(b"half")
            raise OSError("disk full mid-copy")

        monkeypatch.setattr(piper_plus_download.shutil, "copyfile", _failing_copy)

        with pytest.raises(OSError, match="disk full mid-copy"):
            piper_plus_download._link_or_copy_file(src, dst)

        assert dst.read_bytes() == b"existing-intact-model"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["dst.onnx", "src.onnx"]

        cfg = tmp_path / "dst.onnx.json"
        cfg.write_text('{"intact": true}', encoding="utf-8")
        monkeypatch.setattr(
            piper_plus_download.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(PermissionError("locked")),
        )
        with pytest.raises(PermissionError, match="locked"):
            piper_plus_download._write_text_atomic(cfg, '{"broken": false}')

        assert cfg.read_text(encoding="utf-8") == '{"intact": true}'
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "dst.onnx",
            "dst.onnx.json",
            "src.onnx",
        ]

    def test_rollback_logs_warning_when_rmtree_fails_and_preserves_install_error(
        self, tmp_path, monkeypatch
    ):
        """Ensure failed rollback cleanup logs a warning without masking VoiceInstallError."""
        voices_root = tmp_path / "voices"
        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )

        def _fail_write(_install_dir, _metadata):
            raise OSError("metadata write failed")

        def _fail_rmtree(_path):
            raise PermissionError("file locked on Windows")

        monkeypatch.setattr(piper_plus_download.voice_metadata, "write", _fail_write)
        monkeypatch.setattr(piper_plus_download.shutil, "rmtree", _fail_rmtree)
        piper_plus_download.log.warning.reset_mock()

        voice = get_all_piper_plus_voices(voices_root)[0]
        downloader = PiperPlusVoiceDownloader(voice, success_callback=lambda: None)
        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", b"new-bytes"),
            "config.json": self._write_temp(tmp_path, "config.json", b"{}"),
        }

        with pytest.raises(piper_plus_download.VoiceInstallError) as exc_info:
            downloader._install(result)

        assert isinstance(exc_info.value.__cause__, OSError)
        assert "metadata write failed" in str(exc_info.value.__cause__)
        assert piper_plus_download.log.warning.called

    @pytest.mark.parametrize(
        "bad_config_bytes",
        [b"[]", b'"not-a-dict"', b"{malformed"],
    )
    def test_rejects_non_dict_or_malformed_config_and_missing_keys(
        self, tmp_path, monkeypatch, bad_config_bytes
    ):
        """Ensure non-dict JSON configs and missing result keys raise VoiceInstallError."""
        voices_root = tmp_path / "voices"
        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )
        voice = get_all_piper_plus_voices(voices_root)[0]
        downloader = PiperPlusVoiceDownloader(voice, success_callback=lambda: None)

        with pytest.raises(piper_plus_download.VoiceInstallError):
            downloader._install({})

        result = {
            "model.onnx": self._write_temp(tmp_path, "model.onnx", b"\x00"),
            "config.json": self._write_temp(tmp_path, "config.json", bad_config_bytes),
        }
        with pytest.raises(piper_plus_download.VoiceInstallError):
            downloader._install(result)

        assert not voices_root.exists()

    def test_download_work_forwards_per_file_progress(self, tmp_path, monkeypatch):
        """Ensure _download_work forwards streaming chunk percentages to update_progress."""
        voices_root = tmp_path / "voices"
        dl_dir = tmp_path / "dl"
        dl_dir.mkdir()
        monkeypatch.setattr(
            piper_plus_download, "DENGJEN_PIPER_PLUS_VOICES_DIR", str(voices_root)
        )
        voice = get_all_piper_plus_voices(voices_root)[0]
        downloader = PiperPlusVoiceDownloader(voice, success_callback=lambda: None)
        downloader.download_dir = str(dl_dir)
        reported = []
        downloader.update_progress = reported.append
        downloader._report_progress = lambda pct, _msg: reported.append(pct)

        def _fake_download(_spec, _rel, _sha, target_path, progress_callback=None):
            progress_callback(50)
            Path(target_path).write_bytes(b"ok")

        monkeypatch.setattr(piper_plus_download, "_download_to_file", _fake_download)

        out = downloader._download_work()
        assert set(out) == {"model.onnx", "config.json"}
        assert reported == [0, 25, 50, 50, 75, 100]
