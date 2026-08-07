# coding: utf-8
"""
Tests for voice_download.py: the piper-voice metadata parsing, voice-key
derivation, tar-archive install, and the non-GUI parts of the download
orchestration (redirect following, hashing, progress reporting, success/
failure branching).

Deliberately out of scope: voice_manager.py, components.py, and the
GlobalPlugin itself (see issue #65) — they subclass real wx widgets
(wx.ListCtrl, the vendored sized_controls.SizedDialog) that a MagicMock `wx`
can't stand in for as a base class. conftest.py registers
`dengjen_tts_global_plugin` as a package stub exposing only the names its
__init__.py re-exports, without running that file (which would pull in the
GUI modules). Network access is never exercised: `request` (mureq, the
vendored HTTP client) is monkeypatched per-test with canned responses.
"""

import hashlib
import io
import json
import os
import shutil
import tarfile
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

import addonHandler

# In production this runs once, in the package __init__.py, before anything
# that uses `_(...)` is ever imported. We load voice_download.py directly
# without that __init__.py running, so it has to happen here instead.
addonHandler.initTranslation()

voice_download = load_module_from_path(
    "dengjen_tts_global_plugin._voice_download_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "voice_download.py"),
    package="dengjen_tts_global_plugin",
)

PiperVoice = voice_download.PiperVoice
PiperVoiceFile = voice_download.PiperVoiceFile
PiperVoiceLanguage = voice_download.PiperVoiceLanguage
PiperVoiceQualityLevel = voice_download.PiperVoiceQualityLevel
PiperVoiceDownloader = voice_download.PiperVoiceDownloader
PiperRTVoiceDownloader = voice_download.PiperRTVoiceDownloader


class _FakeResponse:
    """Stands in for a mureq Response: status/headers/chunked-read/json."""

    def __init__(self, status=200, headers=None, body=b"", json_data=None):
        self.status = status
        self._headers = headers or {}
        self._body = io.BytesIO(body)
        self._json_data = json_data

    def getheader(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, size=-1):
        return self._body.read(size)

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"status {self.status}")


class _FakeMureq:
    """Stands in for the `mureq` module voice_download imports as `request`.

    `get_responses` feeds sequential calls to `.get()`; `stream_responses`
    feeds sequential `.yield_response()` calls (one per redirect hop).
    """

    def __init__(self, get_responses=None, stream_responses=None):
        self._get_responses = list(get_responses or [])
        self._stream_responses = list(stream_responses or [])
        self.get_urls = []
        self.yield_urls = []

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        return self._get_responses.pop(0)

    @contextmanager
    def yield_response(self, method, url, **kwargs):
        self.yield_urls.append(url)
        assert self._stream_responses, "no more fake stream responses queued"
        yield self._stream_responses.pop(0)


def _language(code="en_US", family="en"):
    return PiperVoiceLanguage(
        code=code,
        family=family,
        region="US",
        name_native="English",
        name_english="English",
        country_english="United States",
    )


def _piper_voice(key="en_US-lessac-medium", has_rt_variant=False, files=None):
    return PiperVoice(
        key=key,
        name="lessac",
        quality=PiperVoiceQualityLevel.Medium,
        num_speakers=1,
        speaker_id_map={},
        language=_language(),
        files=files or [],
        has_rt_variant=has_rt_variant,
    )


class TestPiperVoiceDataclasses:
    def test_file_derives_name_and_download_url_from_path(self):
        f = PiperVoiceFile(file_path="en/en_US-lessac-medium.onnx", size_in_bytes=10, md5hash="x")
        assert f.name == "en_US-lessac-medium.onnx"
        assert f.download_url == f"{voice_download.PIPER_VOICE_DOWNLOAD_URL_PREFIX}/en/en_US-lessac-medium.onnx"

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("v/voice.onnx", voice_download.PiperVoiceFileType.Onnx),
            ("v/voice.onnx.json", voice_download.PiperVoiceFileType.Config),
            ("v/MODEL_CARD", voice_download.PiperVoiceFileType.ModelCard),
        ],
    )
    def test_file_type_from_suffix(self, path, expected):
        f = PiperVoiceFile(file_path=path, size_in_bytes=10, md5hash="x")
        assert f.type == expected

    def test_file_type_raises_for_unknown_suffix(self):
        f = PiperVoiceFile(file_path="v/voice.txt", size_in_bytes=10, md5hash="x")
        with pytest.raises(ValueError):
            f.type

    def test_language_str_uses_dash_not_underscore(self):
        assert str(_language(code="en_US")) == "en-US"

    def test_language_equality_and_hash_are_by_code(self):
        a = _language(code="en_US")
        b = _language(code="en_US", family="different")
        assert a == b
        assert hash(a) == hash(b)

    def test_language_is_not_equal_to_an_unrelated_type(self):
        assert _language() != "en_US"

    def test_quality_level_str_is_title_cased(self):
        assert str(PiperVoiceQualityLevel.XLow) == "X Low"

    def test_language_description_includes_native_name_when_not_english(self):
        lang = PiperVoiceLanguage(
            code="de_DE", family="de", region="DE",
            name_native="Deutsch", name_english="German", country_english="Germany",
        )
        assert lang.description == "German (Germany) , de-DE, Deutsch"

    def test_language_description_omits_native_name_when_already_english(self):
        assert _language().description == "English (United States), en-US"

    def test_from_list_of_dicts_builds_voices_sorted_by_language_family(self):
        data = [
            {
                "key": "de_DE-thorsten-medium",
                "name": "thorsten",
                "quality": "medium",
                "num_speakers": 1,
                "speaker_id_map": {},
                "language": {
                    "code": "de_DE", "family": "de", "region": "DE",
                    "name_native": "Deutsch", "name_english": "German", "country_english": "Germany",
                },
                "files": {"de/thorsten.onnx": {"size_bytes": 5, "md5_digest": "a"}},
                "has_rt_variant": False,
                "standard_variant_installed": False,
                "fast_variant_installed": False,
            },
            {
                "key": "en_US-lessac-medium",
                "name": "lessac",
                "quality": "medium",
                "num_speakers": 1,
                "speaker_id_map": {},
                "language": {
                    "code": "en_US", "family": "en", "region": "US",
                    "name_native": "English", "name_english": "English", "country_english": "United States",
                },
                "files": {"en/lessac.onnx": {"size_bytes": 5, "md5_digest": "b"}},
                "has_rt_variant": True,
                "standard_variant_installed": False,
                "fast_variant_installed": False,
            },
        ]
        voices = PiperVoice.from_list_of_dicts(data)
        assert [v.language.family for v in voices] == ["de", "en"]
        assert voices[1].files[0].file_path == "en/lessac.onnx"
        assert voices[1].quality is PiperVoiceQualityLevel.Medium

    def test_get_preview_url(self):
        voice = _piper_voice()
        assert voice.get_preview_url(speaker_idx=2) == (
            f"{voice_download.PIPER_SAMPLES_URL_PREFIX}/en/en_US/lessac/medium/speaker_2.mp3"
        )

    def test_get_rt_variant_download_url_requires_rt_variant(self):
        voice = _piper_voice(has_rt_variant=False)
        with pytest.raises(ValueError):
            voice.get_rt_variant_download_url()

    def test_get_rt_variant_download_url(self):
        voice = _piper_voice(key="en_US-lessac-medium", has_rt_variant=True)
        assert voice.get_rt_variant_download_url() == (
            f"{voice_download.RT_VOICE_DOWNLOAD_URL_PREFIX}/en_US-lessac+RT-medium.tar.gz"
        )


class TestVoiceInfoRegex:
    """VOICE_INFO_REGEX identifies language/name/quality from an archive's
    or a bundled .onnx file's filename stem."""

    @pytest.mark.parametrize(
        "stem,language,name,quality",
        [
            ("en_US-lessac-medium", "en_US", "lessac", "medium"),
            ("en_US-amy-medium", "en_US", "amy", "medium"),
            ("en_GB-southern_english_female-low", "en_GB", "southern_english_female", "low"),
            ("vi_VN-vivos-x_low", "vi_VN", "vivos", "x_low"),
            ("de_DE-thorsten-medium", "de_DE", "thorsten", "medium"),
        ],
    )
    def test_parses_canonical_voice_name(self, stem, language, name, quality):
        m = voice_download.VOICE_INFO_REGEX.match(stem)
        assert m is not None, f"Failed to parse {stem!r}"
        info = m.groupdict()
        assert info["language"] == language
        assert info["name"] == name
        assert info["quality"] == quality

    @pytest.mark.parametrize(
        "stem,name",
        [
            # Regression: digits in the name, e.g. MLS dataset speaker IDs.
            # Originally reported as mush42/sonata-nvda#2.
            ("pl_PL-mls_6892-low", "mls_6892"),
            ("fr_FR-mls_1840-low", "mls_1840"),
            # The +RT (real-time) variant suffix.
            ("en_US-amy+RT-medium", "amy+RT"),
            ("en_US-lessac+RT-medium", "lessac+RT"),
        ],
    )
    def test_parses_names_with_digits_and_rt_suffix(self, stem, name):
        m = voice_download.VOICE_INFO_REGEX.match(stem)
        assert m is not None, f"Failed to parse {stem!r}"
        assert m.groupdict()["name"] == name

    @pytest.mark.parametrize("quality", ["high", "medium", "low", "x-low", "x_low"])
    def test_parses_every_supported_quality_tier(self, quality):
        m = voice_download.VOICE_INFO_REGEX.match(f"en_US-amy-{quality}")
        assert m is not None
        assert m.groupdict()["quality"] == quality


class TestVoiceKeyDerivation:
    @pytest.mark.parametrize(
        "stem,expected",
        [
            ("en_US-lessac-medium", "en_US-lessac-medium"),
            ("en_US-lessac+RT-medium", "en_US-lessac+RT-medium"),
            ("de_DE-thorsten-x_low", "de_DE-thorsten-x_low"),
            ("pl_PL-mls_6892-low", "pl_PL-mls_6892-low"),
        ],
    )
    def test_from_filename_normalizes_matching_stems(self, stem, expected):
        assert voice_download._voice_key_from_filename(stem) == expected

    @pytest.mark.parametrize(
        "stem",
        [
            "aivars",              # upstream #47 — no separators at all
            "voice",               # single word
            "aivars-medium",       # missing language part
            "en-foo-banana",       # quality not in {high,medium,low,x-low,x_low}
        ],
    )
    def test_from_filename_returns_none_when_it_does_not_match(self, stem):
        assert voice_download._voice_key_from_filename(stem) is None

    @pytest.mark.parametrize(
        "config,expected",
        [
            (
                {"language": {"code": "en-us"}, "dataset": "lessac", "audio": {"quality": "medium"}},
                "en_US-lessac-medium",
            ),
            (
                # Dashes inside dataset/quality would break the X-Y-Z voice_key
                # structure if left unreplaced (upstream #47's fallback path).
                {"language": {"code": "en_US"}, "dataset": "my-dataset", "audio": {"quality": "x-low"}},
                "en_US-my_dataset-x_low",
            ),
        ],
    )
    def test_from_config_derives_key_from_required_fields(self, config, expected):
        assert voice_download._voice_key_from_config(config) == expected

    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"language": {"code": "en_US"}},
            {"language": {"code": "en_US"}, "dataset": "x"},
            {"dataset": "x", "audio": {"quality": "medium"}},
            {"language": {}, "dataset": "x", "audio": {"quality": "medium"}},
            {"language": "en_US", "dataset": "x", "audio": {"quality": "medium"}},
        ],
    )
    def test_from_config_raises_when_a_required_field_is_missing(self, config):
        with pytest.raises(ValueError, match="missing required fields"):
            voice_download._voice_key_from_config(config)


def _make_tar(tmp_path, name, members):
    """Build a .tar.gz at tmp_path/name from {archive_path: bytes}."""
    tar_path = tmp_path / name
    with tarfile.open(tar_path, "w:gz") as tar:
        for arcname, content in members.items():
            info = tarfile.TarInfo(name=arcname)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return tar_path


class TestInstallVoiceFromTarArchive:
    def test_installs_a_single_onnx_voice_deriving_key_from_filename(self, tmp_path):
        tar_path = _make_tar(tmp_path, "voice.tar.gz", {
            "en_US-lessac-medium.onnx": b"model-bytes",
            "en_US-lessac-medium.onnx.json": b"{}",
            "MODEL_CARD": b"card",
        })
        voices_dir = tmp_path / "voices"
        voice_key = voice_download.install_voice_from_tar_archive(str(tar_path), str(voices_dir))
        assert voice_key == "en_US-lessac-medium"
        installed = voices_dir / voice_key
        assert (installed / "en_US-lessac-medium.onnx").read_bytes() == b"model-bytes"
        assert (installed / "en_US-lessac-medium.onnx.json").read_bytes() == b"{}"
        assert (installed / "MODEL_CARD").read_bytes() == b"card"

    def test_multi_onnx_archive_derives_key_from_the_archive_filename(self, tmp_path):
        tar_path = _make_tar(tmp_path, "en_US-lessac-medium.tar.gz", {
            "std/en_US-lessac-medium.onnx": b"a",
            "rt/en_US-lessac+RT-medium.onnx": b"b",
            "std/en_US-lessac-medium.onnx.json": b"{}",
        })
        voice_key = voice_download.install_voice_from_tar_archive(str(tar_path), str(tmp_path / "voices"))
        assert voice_key == "en_US-lessac-medium"

    def test_falls_back_to_config_derived_key_when_filename_does_not_match(self, tmp_path):
        config = {"language": {"code": "en_US"}, "dataset": "custom", "audio": {"quality": "medium"}}
        tar_path = _make_tar(tmp_path, "archive.tar.gz", {
            "weird-name.onnx": json.dumps(config).encode(),  # content unused for onnx
            "weird-name.onnx.json": json.dumps(config).encode(),
        })
        voice_key = voice_download.install_voice_from_tar_archive(str(tar_path), str(tmp_path / "voices"))
        assert voice_key == "en_US-custom-medium"

    def test_raises_when_required_files_are_missing(self, tmp_path):
        tar_path = _make_tar(tmp_path, "voice.tar.gz", {"MODEL_CARD": b"card"})
        with pytest.raises(FileNotFoundError):
            voice_download.install_voice_from_tar_archive(str(tar_path), str(tmp_path / "voices"))


class TestSelectNotInstalledVoices:
    @pytest.fixture
    def installed(self, monkeypatch):
        def _set(keys):
            fake_voices = [type("V", (), {"key": k})() for k in keys]
            monkeypatch.setattr(
                voice_download.DengjenTextToSpeechSystem,
                "load_piper_voices_from_nvda_config_dir",
                classmethod(lambda cls: fake_voices),
            )
        return _set

    def _voice_dict(self, has_rt_variant):
        return {"has_rt_variant": has_rt_variant}

    def test_excludes_voice_when_both_variants_are_installed(self, installed):
        installed(["en_US-lessac-medium", "en_US-lessac+RT-medium"])
        voices = {"en_US-lessac-medium": self._voice_dict(has_rt_variant=True)}
        assert voice_download._select_not_installed_voices(voices) == []

    def test_excludes_standard_only_voice_with_no_rt_variant(self, installed):
        installed(["en_US-lessac-medium"])
        voices = {"en_US-lessac-medium": self._voice_dict(has_rt_variant=False)}
        assert voice_download._select_not_installed_voices(voices) == []

    def test_includes_standard_installed_voice_that_still_has_an_rt_variant_to_offer(self, installed):
        installed(["en_US-lessac-medium"])
        voices = {"en_US-lessac-medium": self._voice_dict(has_rt_variant=True)}
        result = voice_download._select_not_installed_voices(voices)
        assert len(result) == 1
        assert result[0]["standard_variant_installed"] is True
        assert result[0]["fast_variant_installed"] is False

    def test_includes_voice_with_neither_variant_installed(self, installed):
        installed([])
        voices = {"en_US-lessac-medium": self._voice_dict(has_rt_variant=False)}
        result = voice_download._select_not_installed_voices(voices)
        assert len(result) == 1
        assert result[0]["standard_variant_installed"] is False
        assert result[0]["fast_variant_installed"] is False


class TestVoicesCache:
    @pytest.fixture
    def cache_path(self, tmp_path, monkeypatch):
        path = tmp_path / "piper-voices.json"
        monkeypatch.setattr(voice_download, "PIPER_VOICES_JSON_LOCAL_CACHE", str(path))
        return path

    def test_get_voices_from_cache_returns_none_when_file_is_missing(self, cache_path):
        assert voice_download._get_voices_from_cache() is None

    def test_get_available_voices_uses_the_cache_without_going_online(self, cache_path, monkeypatch):
        cache_path.write_text(json.dumps({}), encoding="utf-8")
        fake_request = _FakeMureq()
        monkeypatch.setattr(voice_download, "request", fake_request)
        monkeypatch.setattr(
            voice_download.DengjenTextToSpeechSystem,
            "load_piper_voices_from_nvda_config_dir",
            classmethod(lambda cls: []),
        )
        result = voice_download.get_available_voices(force_online=False)
        assert result == []
        assert fake_request.get_urls == []

    def test_get_available_voices_refreshes_from_both_endpoints_when_forced(self, cache_path, monkeypatch):
        std_payload = {
            "en_US-lessac-medium": {
                "key": "en_US-lessac-medium", "name": "lessac", "quality": "medium",
                "num_speakers": 1, "speaker_id_map": {},
                "language": {
                    "code": "en_US", "family": "en", "region": "US",
                    "name_native": "English", "name_english": "English", "country_english": "United States",
                },
                "files": {"en/lessac.onnx": {"size_bytes": 5, "md5_digest": "a"}},
            }
        }
        rt_payload = {"some-rt-entry": {"base": "en_US-lessac-medium"}}
        fake_request = _FakeMureq(get_responses=[
            _FakeResponse(status=200, json_data=std_payload),
            _FakeResponse(status=200, json_data=rt_payload),
        ])
        monkeypatch.setattr(voice_download, "request", fake_request)
        monkeypatch.setattr(
            voice_download.DengjenTextToSpeechSystem,
            "load_piper_voices_from_nvda_config_dir",
            classmethod(lambda cls: []),
        )
        result = voice_download.get_available_voices(force_online=True)
        assert [v.key for v in result] == ["en_US-lessac-medium"]
        assert result[0].has_rt_variant is True
        assert fake_request.get_urls == [
            voice_download.PIPER_VOICE_LIST_URL,
            voice_download.RT_VOICE_LIST_URL,
        ]
        assert json.loads(cache_path.read_text(encoding="utf-8"))["en_US-lessac-medium"]["has_rt_variant"] is True


class TestPiperVoiceDownloaderFileTransfer:
    """`_do_download_file` is where redirect/content-type/hash bugs would
    actually surface — HuggingFace serves every file through a redirect."""

    def _file(self, body):
        return PiperVoiceFile(file_path="en/en_US-lessac-medium.onnx", size_in_bytes=len(body), md5hash="unused")

    def test_downloads_and_hashes_a_direct_200_response(self, tmp_path, monkeypatch):
        body = b"piper-model-bytes"
        fake_request = _FakeMureq(stream_responses=[
            _FakeResponse(status=200, headers={"Content-Type": "application/octet-stream"}, body=body),
        ])
        monkeypatch.setattr(voice_download, "request", fake_request)
        file = self._file(body)
        result_file, target, digest = PiperVoiceDownloader._do_download_file(file, str(tmp_path), MagicMock())
        assert result_file is file
        assert open(target, "rb").read() == body
        assert digest == hashlib.md5(body).hexdigest()

    def test_follows_a_redirect_before_downloading(self, tmp_path, monkeypatch):
        body = b"redirected-bytes"
        fake_request = _FakeMureq(stream_responses=[
            _FakeResponse(status=302, headers={"Location": "https://example.com/final.onnx"}),
            _FakeResponse(status=200, headers={"Content-Type": "application/octet-stream"}, body=body),
        ])
        monkeypatch.setattr(voice_download, "request", fake_request)
        file = self._file(body)
        __, target, __ = PiperVoiceDownloader._do_download_file(file, str(tmp_path), MagicMock())
        assert open(target, "rb").read() == body
        assert len(fake_request.yield_urls) == 2

    def test_raises_after_too_many_redirects(self, tmp_path, monkeypatch):
        redirect = _FakeResponse(status=302, headers={"Location": "https://example.com/again"})
        fake_request = _FakeMureq(stream_responses=[redirect] * voice_download.REDIRECT_LIMIT)
        monkeypatch.setattr(voice_download, "request", fake_request)
        file = self._file(b"x")
        with pytest.raises(RuntimeError, match="Too many redirects"):
            PiperVoiceDownloader._do_download_file(file, str(tmp_path), MagicMock())

    def test_raises_on_redirect_without_a_location_header(self, tmp_path, monkeypatch):
        fake_request = _FakeMureq(stream_responses=[_FakeResponse(status=302, headers={})])
        monkeypatch.setattr(voice_download, "request", fake_request)
        file = self._file(b"x")
        with pytest.raises(ValueError, match="Redirect without Location header"):
            PiperVoiceDownloader._do_download_file(file, str(tmp_path), MagicMock())

    def test_raises_on_wrong_content_type(self, tmp_path, monkeypatch):
        fake_request = _FakeMureq(stream_responses=[
            _FakeResponse(status=200, headers={"Content-Type": "text/html"}, body=b"<html/>"),
        ])
        monkeypatch.setattr(voice_download, "request", fake_request)
        file = self._file(b"x")
        with pytest.raises(RuntimeError, match="Wrong content-type"):
            PiperVoiceDownloader._do_download_file(file, str(tmp_path), MagicMock())

    def test_raises_on_non_redirect_error_status(self, tmp_path, monkeypatch):
        fake_request = _FakeMureq(stream_responses=[_FakeResponse(status=404)])
        monkeypatch.setattr(voice_download, "request", fake_request)
        file = self._file(b"x")
        with pytest.raises(RuntimeError, match="Download failed"):
            PiperVoiceDownloader._do_download_file(file, str(tmp_path), MagicMock())

    def test_download_voice_files_collects_a_result_per_file(self, tmp_path, monkeypatch):
        bodies = [b"one", b"two"]
        files = [
            PiperVoiceFile(file_path=f"en/f{i}.onnx", size_in_bytes=len(b), md5hash="unused")
            for i, b in enumerate(bodies)
        ]
        fake_request = _FakeMureq(stream_responses=[
            _FakeResponse(status=200, headers={"Content-Type": "application/octet-stream"}, body=b)
            for b in bodies
        ])
        monkeypatch.setattr(voice_download, "request", fake_request)
        voice = _piper_voice(files=files)
        downloader = PiperVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()
        results = downloader.download_voice_files()
        assert len(results) == 2
        assert downloader.progress_dialog.Update.called


class TestPiperVoiceDownloaderDoneCallback:
    def _downloaded(self, tmp_path, body):
        src = tmp_path / "downloaded.onnx"
        src.write_bytes(body)
        digest = hashlib.md5(body).hexdigest()
        file = PiperVoiceFile(file_path="en/en_US-lessac-medium.onnx", size_in_bytes=len(body), md5hash=digest)
        return file, str(src), digest

    def test_success_copies_files_and_offers_a_restart(self, tmp_path, monkeypatch):
        voices_dir = tmp_path / "voices"
        monkeypatch.setattr(voice_download, "DENGJEN_VOICES_DIR", str(voices_dir))
        monkeypatch.setattr(voice_download.wx, "YES", "YES")
        monkeypatch.setattr(voice_download.gui, "messageBox", MagicMock(return_value="YES"))
        restart_mock = MagicMock()
        monkeypatch.setattr(voice_download.core, "restart", restart_mock)

        voice = _piper_voice(key="en_US-lessac-medium")
        downloader = PiperVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()
        file, src, digest = self._downloaded(tmp_path, b"model-bytes")

        downloader.done_callback([(file, src, digest)])

        installed_file = voices_dir / "en_US-lessac-medium" / file.name
        assert installed_file.read_bytes() == b"model-bytes"
        downloader.success_callback.assert_called_once()
        restart_mock.assert_called_once()

    def test_hash_mismatch_does_not_install_and_reports_failure(self, tmp_path, monkeypatch):
        voices_dir = tmp_path / "voices"
        monkeypatch.setattr(voice_download, "DENGJEN_VOICES_DIR", str(voices_dir))
        messagebox_mock = MagicMock()
        monkeypatch.setattr(voice_download.gui, "messageBox", messagebox_mock)

        voice = _piper_voice(key="en_US-lessac-medium")
        downloader = PiperVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()
        file, src, __ = self._downloaded(tmp_path, b"model-bytes")

        downloader.done_callback([(file, src, "mismatched-hash")])

        assert not voices_dir.exists()
        downloader.success_callback.assert_not_called()
        messagebox_mock.assert_called_once()
        assert "Cannot download" in messagebox_mock.call_args.args[0]

    def test_copy_failure_reports_failure_without_crashing(self, tmp_path, monkeypatch):
        voices_dir = tmp_path / "voices"
        monkeypatch.setattr(voice_download, "DENGJEN_VOICES_DIR", str(voices_dir))
        monkeypatch.setattr(voice_download.shutil, "copy", MagicMock(side_effect=IOError("disk full")))
        messagebox_mock = MagicMock()
        monkeypatch.setattr(voice_download.gui, "messageBox", messagebox_mock)

        voice = _piper_voice(key="en_US-lessac-medium")
        downloader = PiperVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()
        file, src, digest = self._downloaded(tmp_path, b"model-bytes")

        downloader.done_callback([(file, src, digest)])

        downloader.success_callback.assert_not_called()
        messagebox_mock.assert_called_once()

    def test_an_exception_result_is_reported_without_touching_disk(self, tmp_path, monkeypatch):
        voices_dir = tmp_path / "voices"
        monkeypatch.setattr(voice_download, "DENGJEN_VOICES_DIR", str(voices_dir))
        messagebox_mock = MagicMock()
        monkeypatch.setattr(voice_download.gui, "messageBox", messagebox_mock)

        voice = _piper_voice(key="en_US-lessac-medium")
        downloader = PiperVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()

        downloader.done_callback(RuntimeError("network exploded"))

        assert not voices_dir.exists()
        downloader.success_callback.assert_not_called()
        messagebox_mock.assert_called_once()


class TestPiperRTVoiceDownloader:
    def test_construction_requires_an_rt_variant(self):
        voice = _piper_voice(has_rt_variant=False)
        with pytest.raises(ValueError):
            PiperRTVoiceDownloader(voice, success_callback=MagicMock())

    def test_do_download_archive_streams_to_a_file(self, tmp_path, monkeypatch):
        body = b"archive-bytes"
        fake_request = _FakeMureq(stream_responses=[
            _FakeResponse(status=200, headers={"Content-Length": str(len(body))}, body=body),
        ])
        monkeypatch.setattr(voice_download, "request", fake_request)
        target = PiperRTVoiceDownloader._do_download_archive(
            "https://example.com/voice.tar.gz", "voice.tar.gz", str(tmp_path), MagicMock()
        )
        assert open(target, "rb").read() == body

    def test_success_installs_the_archive_and_offers_a_restart(self, tmp_path, monkeypatch):
        voices_dir = tmp_path / "voices"
        monkeypatch.setattr(voice_download, "DENGJEN_VOICES_DIR", str(voices_dir))
        monkeypatch.setattr(voice_download.wx, "YES", "YES")
        monkeypatch.setattr(voice_download.gui, "messageBox", MagicMock(return_value="YES"))
        restart_mock = MagicMock()
        monkeypatch.setattr(voice_download.core, "restart", restart_mock)

        tar_path = _make_tar(tmp_path, "en_US-lessac-medium.tar.gz", {
            "en_US-lessac+RT-medium.onnx": b"rt-model",
            "en_US-lessac+RT-medium.onnx.json": b"{}",
        })
        voice = _piper_voice(key="en_US-lessac-medium", has_rt_variant=True)
        downloader = PiperRTVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()

        downloader.done_callback(str(tar_path))

        installed = voices_dir / "en_US-lessac+RT-medium" / "en_US-lessac+RT-medium.onnx"
        assert installed.read_bytes() == b"rt-model"
        downloader.success_callback.assert_called_once()
        restart_mock.assert_called_once()

    def test_extraction_failure_is_reported_without_crashing(self, tmp_path, monkeypatch):
        voices_dir = tmp_path / "voices"
        monkeypatch.setattr(voice_download, "DENGJEN_VOICES_DIR", str(voices_dir))
        messagebox_mock = MagicMock()
        monkeypatch.setattr(voice_download.gui, "messageBox", messagebox_mock)

        not_a_tar = tmp_path / "corrupt.tar.gz"
        not_a_tar.write_bytes(b"not actually a tar file")
        voice = _piper_voice(key="en_US-lessac-medium", has_rt_variant=True)
        downloader = PiperRTVoiceDownloader(voice, success_callback=MagicMock())
        downloader.progress_dialog = MagicMock()

        downloader.done_callback(str(not_a_tar))

        downloader.success_callback.assert_not_called()
        messagebox_mock.assert_called_once()
