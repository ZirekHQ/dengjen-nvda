"""
Tests for download_infra.py: the backend-agnostic HTTP download machinery
shared by voice_download.py (Piper) and kokoro_download.py (Kokoro) --
redirect following, TLS trust-store-gap fallback, and resumable streaming to
disk.

Network is never exercised: `request` (mureq, the vendored HTTP client) is
monkeypatched per-test with canned responses.
"""

import hashlib
import io
import os
import ssl
from contextlib import contextmanager
from http.client import HTTPException
from unittest.mock import MagicMock

import addonHandler
import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

addonHandler.initTranslation()

# Loaded under a private name deliberately: this file never goes through
# voice_download.py, so reusing the canonical dotted name here would risk
# clobbering the real module or creating test-collection-order dependence.
download_infra = load_module_from_path(
    "dengjen_tts_global_plugin._download_infra_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "download_infra.py"),
    package="dengjen_tts_global_plugin",
)


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
    """Stands in for the `mureq` module download_infra imports as `request`.

    `get_responses` feeds sequential calls to `.get()`; `stream_responses`
    feeds sequential `.yield_response()` calls (one per redirect hop).
    """

    def __init__(self, get_responses=None, stream_responses=None):
        self._get_responses = list(get_responses or [])
        self._stream_responses = list(stream_responses or [])
        self.get_urls = []
        self.yield_urls = []
        self.get_calls = []
        self.yield_calls = []

    def get(self, url, **kwargs):
        self.get_urls.append(url)
        self.get_calls.append(kwargs)
        item = self._get_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @contextmanager
    def yield_response(self, method, url, **kwargs):
        self.yield_urls.append(url)
        self.yield_calls.append(kwargs)
        assert self._stream_responses, "no more fake stream responses queued"
        item = self._stream_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        yield item


def _cert_verification_error():
    """An HTTPException as mureq wraps a TLS trust-store failure, i.e. with
    the original ssl.SSLCertVerificationError preserved as __cause__."""
    exc = HTTPException("certificate verify failed")
    exc.__cause__ = ssl.SSLCertVerificationError(
        "unable to get local issuer certificate"
    )
    return exc


class TestCertVerificationFallback:
    """`get_with_cert_fallback`/`_yield_response_with_cert_fallback` retry
    once against the vendored CA bundle when the OS trust store is missing a
    root CA (issue #132), but must not mask unrelated HTTPExceptions."""

    @pytest.fixture
    def fallback_context(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(download_infra, "_fallback_ssl_context", lambda: sentinel)
        return sentinel

    def test_get_retries_with_fallback_context_on_cert_error(
        self, monkeypatch, fallback_context
    ):
        fake_request = _FakeMureq(
            get_responses=[
                _cert_verification_error(),
                _FakeResponse(status=200, json_data={"ok": True}),
            ]
        )
        monkeypatch.setattr(download_infra, "request", fake_request)

        result = download_infra.get_with_cert_fallback(
            "https://example.com/voices.json"
        )

        assert result.json() == {"ok": True}
        assert len(fake_request.get_calls) == 2
        assert "ssl_context" not in fake_request.get_calls[0]
        assert fake_request.get_calls[1]["ssl_context"] is fallback_context

    def test_get_does_not_retry_on_unrelated_http_exception(self, monkeypatch):
        fake_request = _FakeMureq(get_responses=[HTTPException("connection reset")])
        monkeypatch.setattr(download_infra, "request", fake_request)

        with pytest.raises(HTTPException, match="connection reset"):
            download_infra.get_with_cert_fallback("https://example.com/voices.json")

        assert len(fake_request.get_calls) == 1

    def test_yield_response_retries_with_fallback_context_on_cert_error(
        self, monkeypatch, fallback_context
    ):
        fake_request = _FakeMureq(
            stream_responses=[
                _cert_verification_error(),
                _FakeResponse(status=200, body=b"voice-bytes"),
            ]
        )
        monkeypatch.setattr(download_infra, "request", fake_request)

        with download_infra._yield_response_with_cert_fallback(
            "GET", "https://example.com/voice.onnx"
        ) as response:
            assert response.read() == b"voice-bytes"

        assert len(fake_request.yield_calls) == 2
        assert "ssl_context" not in fake_request.yield_calls[0]
        assert fake_request.yield_calls[1]["ssl_context"] is fallback_context

    def test_yield_response_does_not_retry_on_unrelated_http_exception(
        self, monkeypatch
    ):
        fake_request = _FakeMureq(stream_responses=[HTTPException("connection reset")])
        monkeypatch.setattr(download_infra, "request", fake_request)

        with (
            pytest.raises(HTTPException, match="connection reset"),
            download_infra._yield_response_with_cert_fallback(
                "GET", "https://example.com/voice.onnx"
            ),
        ):
            pass

        assert len(fake_request.yield_calls) == 1

    def test_fallback_ssl_context_loads_the_vendored_cacert_bundle(self):
        download_infra._fallback_ssl_context.cache_clear()
        context = download_infra._fallback_ssl_context()
        assert isinstance(context, ssl.SSLContext)


class TestResumablePartialSize:
    """`resumable_partial_size` decides whether a leftover file from a
    previous attempt is safe to resume from (issue #167)."""

    def test_returns_zero_when_no_partial_exists(self, tmp_path):
        target = tmp_path / "voice.onnx"
        assert download_infra.resumable_partial_size(str(target), 100) == 0

    def test_returns_existing_size_when_smaller_than_expected(self, tmp_path):
        target = tmp_path / "voice.onnx"
        target.write_bytes(b"x" * 40)
        assert download_infra.resumable_partial_size(str(target), 100) == 40

    def test_discards_a_partial_at_or_past_the_expected_size(self, tmp_path):
        target = tmp_path / "voice.onnx"
        target.write_bytes(b"x" * 100)
        assert download_infra.resumable_partial_size(str(target), 100) == 0

    def test_resumes_regardless_of_size_when_expected_size_is_unknown(self, tmp_path):
        target = tmp_path / "voice.tar.gz"
        target.write_bytes(b"x" * 100)
        assert download_infra.resumable_partial_size(str(target), 0) == 100


class TestStreamToFileResume:
    """`stream_to_file` appends to a partial file when the server honors the
    Range request (206), and restarts from scratch when it doesn't (issue #167)."""

    def test_appends_and_extends_the_hash_when_the_server_sends_206(self, tmp_path):
        target = tmp_path / "voice.onnx"
        target.write_bytes(b"already-")
        response = _FakeResponse(status=206, body=b"downloaded")
        hasher = hashlib.md5(usedforsecurity=False)

        download_infra.stream_to_file(
            response, str(target), 18, MagicMock(), hasher, resume_offset=8
        )

        assert target.read_bytes() == b"already-downloaded"
        assert hasher.hexdigest() == hashlib.md5(b"already-downloaded").hexdigest()

    def test_overwrites_from_scratch_when_the_server_ignores_the_range(self, tmp_path):
        target = tmp_path / "voice.onnx"
        target.write_bytes(b"stale-partial-bytes")
        response = _FakeResponse(status=200, body=b"full-body")
        hasher = hashlib.md5(usedforsecurity=False)

        download_infra.stream_to_file(
            response, str(target), 9, MagicMock(), hasher, resume_offset=20
        )

        assert target.read_bytes() == b"full-body"
        assert hasher.hexdigest() == hashlib.md5(b"full-body").hexdigest()


class TestFollowRedirectsRangeSupport:
    """`follow_redirects` forwards a Range header for resumed downloads and
    accepts 206 Partial Content as a terminal (non-redirect) status (issue #167)."""

    def test_forwards_headers_to_the_underlying_request(self, monkeypatch):
        fake_request = _FakeMureq(
            stream_responses=[
                _FakeResponse(
                    status=206,
                    headers={"Content-Type": "application/octet-stream"},
                    body=b"rest-of-file",
                ),
            ]
        )
        monkeypatch.setattr(download_infra, "request", fake_request)

        with download_infra.follow_redirects(
            "https://example.com/voice.onnx",
            "voice.onnx",
            headers={"Range": "bytes=8-"},
        ) as response:
            assert response.read() == b"rest-of-file"

        assert fake_request.yield_calls[0]["headers"] == {"Range": "bytes=8-"}

    def test_accepts_206_as_a_terminal_status(self, monkeypatch):
        fake_request = _FakeMureq(
            stream_responses=[
                _FakeResponse(
                    status=206,
                    headers={"Content-Type": "application/octet-stream"},
                    body=b"rest-of-file",
                ),
            ]
        )
        monkeypatch.setattr(download_infra, "request", fake_request)

        with download_infra.follow_redirects(
            "https://example.com/voice.onnx", "voice.onnx"
        ) as response:
            assert response.status == 206
