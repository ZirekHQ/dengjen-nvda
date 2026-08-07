# coding: utf-8
"""
conftest.py for the GUI smoke tests -- these import the REAL wxPython.

Deliberately not part of tests/: that tree's conftest.py installs a
types.ModuleType stub as `wx` for the whole process, and a stub cannot serve
as a base class for wx.ListCtrl / SizedDialog subclasses. Same reason
tests_contract/ is separate (it needs the real `grpc` that tests/ mocks).
pytest.ini's testpaths=tests keeps this directory out of a bare `pytest`, so
the two never collide in one process. Run it with `pytest tests_gui/`.

NVDA itself is still stubbed -- there is no pip-installable NVDA -- so this
tree calls nvda_stubs.install(stub_wx=False): every NVDA module faked,
`wx` left alone.

Windows-only: wxPython ships no Linux wheels on PyPI, and voice_manager.py
imports winsound and the vendored cp313-win_amd64 miniaudio. collect_ignore_glob
skips the tree cleanly elsewhere rather than erroring during collection.
"""

import os
import sys
from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest

collect_ignore_glob = [] if sys.platform == "win32" else ["test_*.py"]

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

if sys.platform == "win32":
    from tests.nvda_stubs import install

    install(stub_wx=False)

    import wx
    import gui


@pytest.fixture(scope="session")
def wx_app():
    """One wx.App per process -- constructing a second one raises."""
    app = wx.App()
    yield app
    app.Destroy()


@pytest.fixture(autouse=True)
def sync_call_after(monkeypatch):
    """wx.CallAfter only fires from a running event loop; these tests have
    none, so queued callbacks would silently never run. Run them inline,
    matching what the stub `wx` in tests/ already does."""
    monkeypatch.setattr(wx, "CallAfter", lambda func, *a, **kw: func(*a, **kw))


class _SyncExecutor:
    """Stand-in for voice_download.THREAD_POOL_EXECUTOR / aio.THREADED_EXECUTOR:
    runs the callable on the calling thread and hands back a settled Future, so
    done-callbacks are assertable inline."""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirrors Executor semantics
            future.set_exception(exc)
        return future


@pytest.fixture
def sync_executor():
    return _SyncExecutor()


@pytest.fixture
def nvda_gui(wx_app, monkeypatch):
    """A real wx parent for the dialogs under test.

    gui.mainFrame is a MagicMock in the stubs, and wx will not accept a mock
    as a window parent -- SizedDialog(gui.mainFrame, ...) raises. So swap in a
    real Frame, and give sysTrayIcon.menu a real wx.Menu so the GlobalPlugin's
    Append/DestroyItem calls are genuinely exercised.

    runScriptModalDialog stays a no-op: it is what would otherwise show a
    modal and block the run forever.
    """
    frame = wx.Frame(None)
    frame.sysTrayIcon = MagicMock()
    frame.sysTrayIcon.menu = wx.Menu()
    monkeypatch.setattr(gui, "mainFrame", frame)
    # gui.messageBox wraps wx.MessageBox, which answers wx.YES/wx.NO/wx.OK/
    # wx.CANCEL -- not the wx.ID_* values ShowModal() returns -- and the
    # add-on compares against wx.YES.
    monkeypatch.setattr(gui, "messageBox", MagicMock(return_value=wx.YES))
    monkeypatch.setattr(gui, "runScriptModalDialog", MagicMock())
    yield frame
    frame.Destroy()


@pytest.fixture(scope="session")
def gui_plugin_package():
    """The real dengjen_tts_global_plugin, __init__.py executed.

    That execution is what supplies both the GlobalPlugin class and the
    package-level re-exports (DengjenTextToSpeechSystem, DENGJEN_VOICES_DIR,
    helpers, aio) that voice_manager.py reaches via `from . import ...`, so
    this tree needs no hand-built package stub. It also calls
    addonHandler.initTranslation(), which installs `_`.
    """
    import dengjen_tts_global_plugin

    return dengjen_tts_global_plugin
