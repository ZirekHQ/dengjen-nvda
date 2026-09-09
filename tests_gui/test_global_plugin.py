"""
Menu lifecycle and startup-check tests for globalPlugins/__init__.py against
real wxPython.

The risk in this file is the menu item: it is appended to NVDA's system tray
menu in __init__ and destroyed in terminate(), and a leak there means a
duplicated or dangling entry after an add-on reload. gui.mainFrame's
sysTrayIcon.menu is a real wx.Menu here, so Append/DestroyItem are genuinely
exercised.
"""

import contextlib
import sys
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)

import gui
import wx


@pytest.fixture
def plugin_module(gui_plugin_package):
    return gui_plugin_package


@pytest.fixture
def no_installed_voices(plugin_module, monkeypatch):
    monkeypatch.setattr(
        plugin_module.DengjenTextToSpeechSystem,
        "load_all_voices_from_nvda_config_dir",
        classmethod(lambda cls, backend: iter([])),
    )


@pytest.fixture
def one_installed_voice(plugin_module, monkeypatch):
    monkeypatch.setattr(
        plugin_module.DengjenTextToSpeechSystem,
        "load_all_voices_from_nvda_config_dir",
        classmethod(lambda cls, backend: iter([MagicMock()])),
    )


@pytest.fixture
def plugin(plugin_module, nvda_gui):
    instance = plugin_module.GlobalPlugin()
    yield instance
    with contextlib.suppress(Exception):
        instance.terminate()


class TestMenuLifecycle:
    def test_global_plugin_is_a_real_class(self, plugin_module):

        assert isinstance(plugin_module.GlobalPlugin, type)

    def test_it_appends_one_menu_item(self, plugin, nvda_gui):
        assert nvda_gui.sysTrayIcon.menu.GetMenuItemCount() == 1

    def test_the_item_is_labelled_for_the_voice_manager(self, plugin, nvda_gui):
        label = nvda_gui.sysTrayIcon.menu.GetMenuItems()[0].GetItemLabelText()
        assert "voice manager" in label.lower()

    def test_terminate_removes_the_item(self, plugin, nvda_gui):
        plugin.terminate()
        assert nvda_gui.sysTrayIcon.menu.GetMenuItemCount() == 0

    def test_terminate_twice_does_not_raise(self, plugin):
        plugin.terminate()
        plugin.terminate()

    def test_it_registers_a_post_startup_check(self, plugin, plugin_module):
        plugin_module.core.postNvdaStartup.register.assert_called_with(
            plugin._voice_checker
        )


class TestVoiceCheck:
    """_ask_first_run_voice_action shows a real wx.MessageDialog via
    gui.runScriptModalDialog, which nvda_gui mocks -- so every test here
    that needs a user choice grabs the completion callback from that mock's
    call and fires it directly, the same technique
    tests_gui/test_voice_manager_dialog.py uses for its file dialog."""

    @pytest.fixture(autouse=True)
    def _destroy_the_dialog(self):
        # gui.runScriptModalDialog is mocked here, so the real Destroy() it
        # would otherwise do after the dialog closes never runs.
        yield
        if gui.runScriptModalDialog.called:
            gui.runScriptModalDialog.call_args.args[0].Destroy()

    def _choose(self, retval):
        callback = gui.runScriptModalDialog.call_args.args[1]
        callback(retval)

    def test_it_asks_when_no_voice_is_installed(self, plugin, no_installed_voices):
        plugin._perform_voice_check()
        assert gui.runScriptModalDialog.called

    def test_it_stays_quiet_when_a_voice_is_installed(
        self, plugin, one_installed_voice
    ):
        plugin._perform_voice_check()
        assert not gui.runScriptModalDialog.called

    def test_it_stays_quiet_once_the_manager_has_been_opened(
        self, plugin, no_installed_voices
    ):
        plugin._GlobalPlugin__voice_manager_shown = True
        plugin._perform_voice_check()
        assert not gui.runScriptModalDialog.called

    def test_choosing_manager_opens_it(self, plugin, no_installed_voices, monkeypatch):
        opened = []
        monkeypatch.setattr(plugin, "on_manager", lambda evt: opened.append(evt))
        plugin._perform_voice_check()
        self._choose(wx.ID_YES)
        assert len(opened) == 1

    def test_choosing_local_file_installs_from_a_local_file(
        self, plugin, plugin_module, no_installed_voices, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            plugin_module,
            "install_voice_from_local_file",
            lambda **kwargs: calls.append(kwargs),
        )
        plugin._perform_voice_check()
        self._choose(wx.ID_NO)
        assert calls == [{"on_installed": plugin._on_first_run_voice_installed}]

    def test_choosing_not_now_does_nothing(
        self, plugin, plugin_module, no_installed_voices, monkeypatch
    ):
        opened = []
        installed = []
        monkeypatch.setattr(plugin, "on_manager", lambda evt: opened.append(evt))
        monkeypatch.setattr(
            plugin_module,
            "install_voice_from_local_file",
            lambda **kwargs: installed.append(kwargs),
        )
        plugin._perform_voice_check()
        self._choose(wx.ID_CANCEL)
        assert opened == []
        assert installed == []


class TestOnFirstRunVoiceInstalled:
    def test_reinitializes_the_active_dengjen_synth(
        self, plugin, plugin_module, monkeypatch
    ):
        # terminate()'s call record can't be read off the mock after this
        # test's own __init__() call below -- that call re-runs
        # NonCallableMock.__init__ on the same instance, which resets its
        # children's call tracking. An independent side effect survives it.
        calls = []
        synth = MagicMock()
        synth.name = "dengjen_neural_voices"
        synth.terminate.side_effect = lambda: calls.append("terminate")
        monkeypatch.setattr(plugin_module.synthDriverHandler, "getSynth", lambda: synth)
        plugin._on_first_run_voice_installed("en_US-amy-low")
        assert calls == ["terminate"]

    def test_leaves_a_different_active_synth_alone(
        self, plugin, plugin_module, monkeypatch
    ):
        synth = MagicMock()
        synth.name = "espeak"
        monkeypatch.setattr(plugin_module.synthDriverHandler, "getSynth", lambda: synth)
        plugin._on_first_run_voice_installed("en_US-amy-low")
        assert not synth.terminate.called
