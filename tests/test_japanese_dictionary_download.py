"""
Tests for japanese_dictionary_download.py: the archive is verified against a
pinned size and sha256 before anything is extracted, extraction is
traversal-safe, and an archive that fails validation never replaces the
installed dictionary. Network is never exercised.
"""

import hashlib
import io
import os
import tarfile
from contextlib import contextmanager
from unittest.mock import MagicMock

import gui
import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

download = load_module_from_path(
    "dengjen_tts_global_plugin._japanese_dictionary_download_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "japanese_dictionary_download.py"),
    package="dengjen_tts_global_plugin",
)


def _archive(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def _valid_members():
    return {
        "naist-jdic/metadata.json": b"{}",
        "naist-jdic/dict.words": b"words",
    }


@pytest.fixture
def pinned(monkeypatch):
    def pin(path):
        data = path.read_bytes()
        monkeypatch.setattr(download, "EXPECTED_SIZE", len(data))
        monkeypatch.setattr(
            download, "EXPECTED_SHA256", hashlib.sha256(data).hexdigest()
        )

    return pin


class TestVerifyArchive:
    def test_accepts_the_pinned_archive(self, tmp_path, pinned):
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())
        pinned(archive)

        download.verify_archive(archive)

    def test_rejects_a_wrong_size(self, tmp_path, pinned, monkeypatch):
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())
        pinned(archive)
        monkeypatch.setattr(download, "EXPECTED_SIZE", archive.stat().st_size + 1)

        with pytest.raises(ValueError, match="size"):
            download.verify_archive(archive)

    def test_rejects_a_wrong_checksum(self, tmp_path, pinned, monkeypatch):
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())
        pinned(archive)
        monkeypatch.setattr(download, "EXPECTED_SHA256", "0" * 64)

        with pytest.raises(ValueError, match="checksum"):
            download.verify_archive(archive)


class TestExtractDictionary:
    def test_installs_the_dictionary_directory(self, tmp_path):
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())
        dest = tmp_path / "dictionaries" / "naist-jdic"

        download.extract_dictionary(archive, dest)

        assert (dest / "metadata.json").read_bytes() == b"{}"
        assert (dest / "dict.words").read_bytes() == b"words"

    def test_replaces_an_existing_installation(self, tmp_path):
        dest = tmp_path / "dictionaries" / "naist-jdic"
        dest.mkdir(parents=True)
        (dest / "stale.bin").write_bytes(b"old")
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())

        download.extract_dictionary(archive, dest)

        assert not (dest / "stale.bin").exists()
        assert (dest / "metadata.json").exists()

    def test_leaves_no_temporary_directory_behind(self, tmp_path):
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())
        dest = tmp_path / "dictionaries" / "naist-jdic"

        download.extract_dictionary(archive, dest)

        assert [p.name for p in dest.parent.iterdir()] == ["naist-jdic"]

    def test_rejects_a_member_that_escapes_the_directory(self, tmp_path):
        members = {**_valid_members(), "../evil.txt": b"x"}
        archive = _archive(tmp_path / "a.tar.gz", members)
        dest = tmp_path / "dictionaries" / "naist-jdic"

        with pytest.raises(tarfile.TarError):
            download.extract_dictionary(archive, dest)

        assert not dest.exists()
        assert not (tmp_path / "evil.txt").exists()
        assert [p.name for p in dest.parent.iterdir()] == []

    def test_rejects_an_archive_without_the_dictionary_metadata(self, tmp_path):
        archive = _archive(tmp_path / "a.tar.gz", {"naist-jdic/dict.words": b"w"})
        dest = tmp_path / "dictionaries" / "naist-jdic"

        with pytest.raises(ValueError, match="metadata"):
            download.extract_dictionary(archive, dest)

        assert not dest.exists()

    def test_a_failed_reinstall_keeps_the_existing_dictionary(self, tmp_path):
        dest = tmp_path / "dictionaries" / "naist-jdic"
        dest.mkdir(parents=True)
        (dest / "metadata.json").write_text("{}", encoding="utf-8")
        archive = _archive(tmp_path / "a.tar.gz", {"naist-jdic/dict.words": b"w"})

        with pytest.raises(ValueError):
            download.extract_dictionary(archive, dest)

        assert (dest / "metadata.json").exists()

    def test_a_failed_replacement_restores_the_existing_dictionary(
        self, tmp_path, monkeypatch
    ):
        dest = tmp_path / "dictionaries" / "naist-jdic"
        dest.mkdir(parents=True)
        (dest / "metadata.json").write_text("old", encoding="utf-8")
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())
        real_replace = os.replace
        calls = []

        def replace_failing_on_install(src, dst):
            calls.append((src, dst))
            if len(calls) == 2:
                raise PermissionError("locked")
            real_replace(src, dst)

        monkeypatch.setattr(download.os, "replace", replace_failing_on_install)

        with pytest.raises(PermissionError):
            download.extract_dictionary(archive, dest)

        assert (dest / "metadata.json").read_text(encoding="utf-8") == "old"
        assert [p.name for p in dest.parent.iterdir()] == ["naist-jdic"]


class TestDownloaderLifecycle:
    @pytest.fixture
    def downloader(self, monkeypatch):
        monkeypatch.setattr(gui, "messageBox", MagicMock())
        instance = download.JapaneseDictionaryDownloader(
            success_callback=MagicMock(), finished_callback=MagicMock()
        )
        instance.progress_dialog = MagicMock()
        return instance

    def test_a_failed_download_reports_finished_without_success(self, downloader):
        downloader.done_callback(RuntimeError("no network"))

        downloader.finished_callback.assert_called_once()
        downloader.success_callback.assert_not_called()

    def test_a_successful_install_reports_success_and_finished(
        self, downloader, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            download, "DENGJEN_JAPANESE_DICTIONARY_DIR", str(tmp_path / "naist-jdic")
        )
        archive = _archive(tmp_path / "a.tar.gz", _valid_members())

        downloader.done_callback({"archive": archive})

        downloader.success_callback.assert_called_once()
        downloader.finished_callback.assert_called_once()


class TestDownloadArchive:
    def _fake_follow_redirects(self, payload, content_length=None):
        @contextmanager
        def follow_redirects(url, label, headers=None):
            response = MagicMock()
            response.getheader.return_value = str(
                len(payload) if content_length is None else content_length
            )
            response.read.side_effect = [payload, b""]
            response.status = 200
            yield response

        return follow_redirects

    def test_writes_the_archive_to_the_target(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            download, "follow_redirects", self._fake_follow_redirects(b"abc")
        )
        target = tmp_path / "a.tar.gz"

        download.download_archive(target, lambda _percent: None)

        assert target.read_bytes() == b"abc"

    def test_honors_a_mirror_override(self, tmp_path, monkeypatch, hosting_overrides):
        hosting_overrides["japanese_dictionary_url"] = "https://mirror.example/jdic.tgz"
        seen = []
        fake = self._fake_follow_redirects(b"abc")

        @contextmanager
        def recording(url, label, headers=None):
            seen.append(url)
            with fake(url, label, headers) as response:
                yield response

        monkeypatch.setattr(download, "follow_redirects", recording)

        download.download_archive(tmp_path / "a.tar.gz", lambda _percent: None)

        assert seen == ["https://mirror.example/jdic.tgz"]

    def test_removes_a_truncated_download(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            download,
            "follow_redirects",
            self._fake_follow_redirects(b"abc", content_length=10),
        )
        target = tmp_path / "a.tar.gz"

        with pytest.raises(RuntimeError):
            download.download_archive(target, lambda _percent: None)

        assert not target.exists()


class TestCatalog:
    def test_reports_installed_only_with_the_dictionary_metadata(
        self, tmp_path, monkeypatch
    ):
        dest = tmp_path / "naist-jdic"
        monkeypatch.setattr(download, "DENGJEN_JAPANESE_DICTIONARY_DIR", str(dest))
        catalog = download.JapaneseDictionaryCatalog()

        assert not catalog.is_installed()
        dest.mkdir()
        assert not catalog.is_installed()
        (dest / "metadata.json").write_text("{}", encoding="utf-8")
        assert catalog.is_installed()
