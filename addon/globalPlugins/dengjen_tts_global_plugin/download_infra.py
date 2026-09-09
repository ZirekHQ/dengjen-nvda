"""Backend-agnostic voice-download machinery: redirect following, TLS
trust-store-gap fallback, and resumable disk streaming. Shared by
voice_download.py (Piper) and kokoro_download.py (Kokoro) -- neither format
is relevant to any of the code in this file.

Also holds BaseVoiceDownloader, the shared download/install/progress-dialog
workflow both backends' downloader classes subclass -- the only part of this
module that imports wx, gui, and core."""

import math
import os
import re
import shutil
import ssl
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from functools import lru_cache, partial
from http.client import HTTPException

import addonHandler
import core
import gui
import wx
from logHandler import log

addonHandler.initTranslation()

from . import DENGJEN_VOICES_DIR, helpers

with helpers.import_bundled_library():
    import mureq as request


THREAD_POOL_EXECUTOR = ThreadPoolExecutor()
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
REDIRECT_LIMIT = 5
DOWNLOAD_CHUNK_SIZE = 4096
CACERT_PATH = os.path.join(helpers.LIB_DIRECTORY, "cacert.pem")


@lru_cache(maxsize=1)
def _fallback_ssl_context():
    return ssl.create_default_context(cafile=CACERT_PATH)


def _is_os_trust_store_gap(exc):

    return isinstance(exc.__cause__, ssl.SSLCertVerificationError)


def get_with_cert_fallback(url, **kwargs):
    try:
        return request.get(url, **kwargs)
    except HTTPException as e:
        if not _is_os_trust_store_gap(e):
            raise
        log.debug(
            "OS trust store missing a root CA; retrying with the vendored CA bundle",
            exc_info=True,
        )
        return request.get(url, ssl_context=_fallback_ssl_context(), **kwargs)


@contextmanager
def _yield_response_with_cert_fallback(method, url, headers=None, **kwargs):
    with ExitStack() as stack:
        try:
            response = stack.enter_context(
                request.yield_response(method, url, headers=headers, **kwargs)
            )
        except HTTPException as e:
            if not _is_os_trust_store_gap(e):
                raise
            log.debug(
                "OS trust store missing a root CA; retrying with the vendored CA bundle",
                exc_info=True,
            )
            response = stack.enter_context(
                request.yield_response(
                    method,
                    url,
                    headers=headers,
                    ssl_context=_fallback_ssl_context(),
                    **kwargs,
                )
            )
        yield response


@contextmanager
def follow_redirects(url, label, headers=None):

    for _redirect in range(REDIRECT_LIMIT):
        with _yield_response_with_cert_fallback(
            "GET", url, headers=headers
        ) as response:
            if response.status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Redirect without Location header.")
                url = urllib.parse.urljoin(url, location)
                continue

            if response.status not in (200, 206):
                raise RuntimeError(
                    f"Download failed for {label} (status {response.status})"
                )

            content_type = response.getheader("Content-Type", "").lower()
            if "text/html" in content_type or "xml" in content_type:
                raise RuntimeError(
                    f"Wrong content-type while downloading {label}: {content_type}"
                )

            yield response
            return

    raise RuntimeError(f"Too many redirects while downloading {label}")


def resumable_partial_size(target_file, expected_size):
    """Bytes of `target_file` already on disk that a Range request can resume from.

    Returns 0 (start fresh) when nothing exists yet, or when a known
    `expected_size` shows the leftover is stale/complete already.
    """
    if not os.path.exists(target_file):
        return 0
    existing_size = os.path.getsize(target_file)
    if expected_size and existing_size >= expected_size:
        return 0
    return existing_size


CONTENT_RANGE_TOTAL_REGEX = re.compile(r"bytes \d+-\d+/(\d+)")


def archive_total_size(response, resume_offset):
    """The archive's full size, for a request that may itself be a resume.

    A 206 reports only the remaining bytes via Content-Length, so the total
    comes from Content-Range's `.../<total>` instead; a fresh 200 reports the
    full size directly.
    """
    if response.status == 206:
        match = CONTENT_RANGE_TOTAL_REGEX.match(response.getheader("Content-Range", ""))
        return int(match.group(1)) if match else resume_offset
    return int(response.getheader("Content-Length", 0))


def stream_to_file(
    response, target_file, total_size, progress_callback, hasher=None, resume_offset=0
):
    """Streams `response` into `target_file`, resuming a prior partial download.

    A resume is only honored when the server actually answered with 206 —
    a 200 despite a Range request means it sent the full body from byte 0,
    so any partial bytes already on disk are discarded and hashed anew.
    """
    is_resuming = resume_offset > 0 and response.status == 206
    downloaded_til_now = resume_offset if is_resuming else 0
    if is_resuming and hasher is not None:
        with open(target_file, "rb") as existing:
            for chunk in iter(partial(existing.read, DOWNLOAD_CHUNK_SIZE), b""):
                hasher.update(chunk)
    with open(target_file, "ab" if is_resuming else "wb") as file_buffer:
        for chunk in iter(partial(response.read, DOWNLOAD_CHUNK_SIZE), b""):
            file_buffer.write(chunk)
            if hasher is not None:
                hasher.update(chunk)
            downloaded_til_now += len(chunk)
            if total_size > 0:
                progress_callback(math.floor((downloaded_til_now / total_size) * 100))


class VoiceInstallError(Exception):
    """Raised by a downloader's `_install` hook to signal a failed install."""


class BaseVoiceDownloader:
    def __init__(self, voice, success_callback):
        self.voice = voice
        self.success_callback = success_callback
        # Stable across instances, so resumable_partial_size can find a prior attempt's file here.
        self.download_dir = os.path.join(DENGJEN_VOICES_DIR, ".downloads", voice.key)
        os.makedirs(self.download_dir, exist_ok=True)
        self.progress_dialog = None

    def update_progress(self, progress):
        self._report_progress(
            progress,
            _("Downloaded: {progress}%").format(progress=progress),
        )

    def _report_progress(self, percent, message):
        # download_work runs on a worker thread (see download() below);
        # wx.ProgressDialog.Update() is not thread-safe, so every call must
        # be marshalled onto the GUI thread via wx.CallAfter.
        wx.CallAfter(self.progress_dialog.Update, percent, message)

    def download(self):
        self.progress_dialog = wx.ProgressDialog(
            title=self._progress_title(),
            message=_("Retrieving download information..."),
            parent=gui.mainFrame,
        )
        self.progress_dialog.CenterOnScreen()
        THREAD_POOL_EXECUTOR.submit(self._download_work).add_done_callback(
            partial(self._done_callback_wrapper, self.done_callback)
        )

    def done_callback(self, result):
        # Runs on the worker thread (add_done_callback fires on whichever
        # thread completes it). _install runs here, not after the
        # wx.CallAfter below, so disk I/O doesn't block the wx event loop.
        has_error = isinstance(result, Exception)
        install_error = None
        if not has_error:
            self._report_progress(0, _("Installing voice"))
            try:
                self._install(result)
            except Exception as exc:
                # A subclass's _install can raise more than VoiceInstallError
                # (e.g. an unwrapped OSError); catching only that type let it
                # escape this worker-thread callback, leaving the dialog open.
                has_error = True
                install_error = exc

        wx.CallAfter(self._on_download_complete, has_error, install_error, result)

    def _on_download_complete(self, has_error, install_error, result):
        self.progress_dialog.Hide()
        self.progress_dialog.Destroy()
        del self.progress_dialog

        if not has_error:
            shutil.rmtree(self.download_dir, ignore_errors=True)
            self.success_callback()
            retval = gui.messageBox(
                self._success_message(),
                _("Voice downloaded"),
                wx.YES_NO | wx.ICON_WARNING,
                parent=gui.mainFrame,
            )
            if retval == wx.YES:
                core.restart()
        else:
            gui.messageBox(
                self._failure_message(),
                _("Download failed"),
                style=wx.ICON_ERROR,
                parent=gui.mainFrame,
            )
            error = install_error if install_error is not None else result
            log.error(f"Failed to download voice.\nException: {error}", exc_info=error)

    @staticmethod
    def _done_callback_wrapper(done_callback, future):
        if done_callback is None:
            return
        try:
            result = future.result()
        except Exception as e:
            done_callback(e)
        else:
            done_callback(result)

    def _download_work(self):
        raise NotImplementedError

    def _install(self, result):
        raise NotImplementedError

    def _progress_title(self):
        raise NotImplementedError

    def _success_message(self):
        raise NotImplementedError

    def _failure_message(self):
        raise NotImplementedError
