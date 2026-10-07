"""Japanese dictionary download/install for Kokoro's j* presets.

The engine only loads a dictionary built by its own jpreprocess version, so the
archive at DEFAULT_DICTIONARY_URL is verified against EXPECTED_SIZE and
EXPECTED_SHA256 before anything is extracted.
"""

import hashlib
import os
import shutil
import tarfile
import tempfile
from functools import partial
from pathlib import Path

import addonHandler
from logHandler import log

addonHandler.initTranslation()

from dengjen_neural_voices.const import DENGJEN_JAPANESE_DICTIONARY_DIR
from dengjen_neural_voices.japanese_dictionary import is_installed

from .download_infra import (
    DOWNLOAD_CHUNK_SIZE,
    BaseVoiceDownloader,
    VoiceInstallError,
    follow_redirects,
    hosting_url,
    stream_to_file,
)

DEFAULT_DICTIONARY_URL = (
    "https://github.com/jpreprocess/jpreprocess/releases/download/v0.15.0/"
    "naist-jdic-jpreprocess.tar.gz"
)
EXPECTED_SIZE = 28668638
EXPECTED_SHA256 = "8a930bbc57bf4adcf521d53544c7dc9ab8ab3aa997a591b1b1608dc5539017b8"
ARCHIVE_NAME = "naist-jdic-jpreprocess.tar.gz"
ARCHIVE_ROOT = "naist-jdic"
DICTIONARY_KEY = "japanese-dictionary"


def download_archive(target_path, progress_callback):
    url = hosting_url("japanese_dictionary_url", DEFAULT_DICTIONARY_URL)
    with follow_redirects(url, ARCHIVE_NAME) as response:
        total_size = int(response.getheader("Content-Length", 0))
        stream_to_file(response, target_path, total_size, progress_callback)
    if total_size and Path(target_path).stat().st_size != total_size:
        Path(target_path).unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded size for {ARCHIVE_NAME} does not match")


def verify_archive(path):
    if Path(path).stat().st_size != EXPECTED_SIZE:
        raise ValueError(f"{ARCHIVE_NAME} has an unexpected size")
    digest = hashlib.sha256()
    with open(path, "rb") as archive:
        for chunk in iter(partial(archive.read, DOWNLOAD_CHUNK_SIZE), b""):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_SHA256:
        raise ValueError(f"{ARCHIVE_NAME} has an unexpected checksum")


def _swap_in(extracted, dest, backup):
    if dest.exists():
        os.replace(dest, backup)
    try:
        os.replace(extracted, dest)
    except OSError:
        if backup.exists():
            os.replace(backup, dest)
        raise


def extract_dictionary(archive_path, dest_dir):
    """Replaces `dest_dir` with the archive's dictionary directory; an archive that
    fails validation leaves `dest_dir` untouched."""
    dest = Path(dest_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".naist-jdic-", dir=dest.parent))
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(staging, filter="data")
        extracted = staging / ARCHIVE_ROOT
        if not (extracted / "metadata.json").is_file():
            raise ValueError("The archive has no dictionary metadata.json")
        _swap_in(extracted, dest, backup=staging / "previous")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


class JapaneseDictionaryDownloader(BaseVoiceDownloader):
    class _Descriptor:
        key = DICTIONARY_KEY

    def __init__(self, success_callback, finished_callback=None):
        super().__init__(self._Descriptor(), success_callback)
        self.finished_callback = finished_callback or (lambda: None)

    def _on_download_complete(self, has_error, install_error, result):
        self.finished_callback()
        super()._on_download_complete(has_error, install_error, result)

    def _progress_title(self):
        return _("Downloading Japanese dictionary")

    def _success_message(self):
        return _(
            "Successfully downloaded the Japanese dictionary.\n"
            "To use Japanese Kokoro voices, you need to restart NVDA.\n"
            "Do you want to restart NVDA now?"
        )

    def _failure_message(self):
        return _(
            "Cannot download the Japanese dictionary.\n"
            "Please check your connection and try again."
        )

    def _download_work(self):
        target = Path(self.download_dir) / ARCHIVE_NAME
        download_archive(target, self.update_progress)
        try:
            verify_archive(target)
        except ValueError:
            target.unlink(missing_ok=True)
            raise
        return {"archive": target}

    def _install(self, result):
        try:
            extract_dictionary(result["archive"], DENGJEN_JAPANESE_DICTIONARY_DIR)
        except (OSError, tarfile.TarError, ValueError) as exc:
            log.exception("Failed to install the Japanese dictionary", exc_info=True)
            raise VoiceInstallError from exc


class JapaneseDictionaryCatalog:
    model_type = "japanese-dictionary"

    def is_installed(self) -> bool:
        return is_installed(DENGJEN_JAPANESE_DICTIONARY_DIR)

    def install(self, success_callback, finished_callback=None) -> None:
        JapaneseDictionaryDownloader(success_callback, finished_callback).download()
