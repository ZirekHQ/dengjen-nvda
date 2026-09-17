"""
Tests for feedback.py: version lookups and browser hand-off for the "Send
feedback" menu, against the NVDA stubs (see conftest.py). versionInfo and
winVersion are never installed here, so the "lookup unavailable" paths are
exercised for free -- only the success paths need a fake module injected.
"""

import os
import sys
import types
from unittest.mock import MagicMock

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

feedback = load_module_from_path(
    "dengjen_tts_global_plugin._feedback_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "feedback.py"),
    package="dengjen_tts_global_plugin",
)


class TestAddonVersion:
    def test_returns_the_manifest_version(self, monkeypatch):
        addon = types.SimpleNamespace(manifest={"version": "4.0.1"})
        monkeypatch.setattr(
            feedback.addonHandler, "getCodeAddon", lambda: addon, raising=False
        )
        assert feedback._addon_version() == "4.0.1"

    def test_returns_none_when_the_lookup_fails(self, monkeypatch):
        def raise_lookup():
            raise RuntimeError("no code addon")

        monkeypatch.setattr(
            feedback.addonHandler, "getCodeAddon", raise_lookup, raising=False
        )
        assert feedback._addon_version() is None


class TestNvdaVersion:
    def test_returns_the_version_string(self, monkeypatch):
        fake = types.ModuleType("versionInfo")
        fake.version = "2026.1"
        monkeypatch.setitem(sys.modules, "versionInfo", fake)
        assert feedback._nvda_version() == "2026.1"

    def test_returns_none_when_unavailable(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "versionInfo", raising=False)
        assert feedback._nvda_version() is None


class TestWindowsVersion:
    def test_returns_the_version_string(self, monkeypatch):
        fake = types.ModuleType("winVersion")
        fake.getWinVer = lambda: "Windows 11 (10.0.22631)"
        monkeypatch.setitem(sys.modules, "winVersion", fake)
        assert feedback._windows_version() == "Windows 11 (10.0.22631)"

    def test_returns_none_when_unavailable(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "winVersion", raising=False)
        assert feedback._windows_version() is None


class TestOpenUrl:
    """os.startfile is Windows-only, so it does not exist to patch on the
    Linux leg of this suite -- raising=False lets monkeypatch add it instead
    of requiring it to already be there."""

    def test_hands_the_url_to_the_os(self, monkeypatch):
        calls = []
        monkeypatch.setattr(feedback.os, "startfile", calls.append, raising=False)
        messagebox_mock = MagicMock()
        monkeypatch.setattr(feedback.gui, "messageBox", messagebox_mock)

        feedback._open_url("https://example.com/issues/new")

        assert calls == ["https://example.com/issues/new"]
        assert not messagebox_mock.called

    def test_shows_the_url_when_the_os_cannot_open_it(self, monkeypatch):
        def raise_oserror(url):
            raise OSError("no application is associated")

        monkeypatch.setattr(feedback.os, "startfile", raise_oserror, raising=False)
        messagebox_mock = MagicMock()
        monkeypatch.setattr(feedback.gui, "messageBox", messagebox_mock)

        feedback._open_url("https://example.com/issues/new")

        assert messagebox_mock.called
        message = messagebox_mock.call_args.args[0]
        assert "https://example.com/issues/new" in message


class TestOpenBugReport:
    def test_builds_the_url_from_the_known_versions_and_opens_it(self, monkeypatch):
        monkeypatch.setattr(feedback, "_addon_version", lambda: "4.0.1")
        monkeypatch.setattr(feedback, "_nvda_version", lambda: "2026.1")
        monkeypatch.setattr(feedback, "_windows_version", lambda: "Windows 11")
        opened = []
        monkeypatch.setattr(feedback, "_open_url", opened.append)

        feedback.open_bug_report()

        assert opened == [
            feedback.build_bug_report_url(
                addon_version="4.0.1",
                nvda_version="2026.1",
                windows_version="Windows 11",
            )
        ]


class TestOpenFeatureRequest:
    def test_opens_the_feature_request_url(self, monkeypatch):
        opened = []
        monkeypatch.setattr(feedback, "_open_url", opened.append)

        feedback.open_feature_request()

        assert opened == [feedback.build_feature_request_url()]
