# coding: utf-8
"""
Menu lifecycle and startup-check tests for globalPlugins/__init__.py against
real wxPython.

The risk in this file is the menu item: it is appended to NVDA's system tray
menu in __init__ and destroyed in terminate(), and a leak there means a
duplicated or dangling entry after an add-on reload. gui.mainFrame's
sysTrayIcon.menu is a real wx.Menu here, so Append/DestroyItem are genuinely
exercised.
"""

import sys
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)

import wx


@pytest.fixture
def plugin_module(gui_plugin_package):
    return gui_plugin_package


@pytest.fixture
def no_installed_voices(plugin_module, monkeypatch):
    monkeypatch.setattr(
        plugin_module.DengjenTextToSpeechSystem,
        "load_piper_voices_from_nvda_config_dir",
        classmethod(lambda cls, backend: iter([])),
    )


@pytest.fixture
def one_installed_voice(plugin_module, monkeypatch):
    monkeypatch.setattr(
        plugin_module.DengjenTextToSpeechSystem,
        "load_piper_voices_from_nvda_config_dir",
        classmethod(lambda cls, backend: iter([MagicMock()])),
    )


@pytest.fixture
def plugin(plugin_module, nvda_gui):
    instance = plugin_module.GlobalPlugin()
    yield instance
    try:
        instance.terminate()
    except Exception:
        pass


class TestMenuLifecycle:
    def test_global_plugin_is_a_real_class(self, plugin_module):
        # Guards the stub: subclassing a MagicMock() would silently yield a
        # mock here, and every assertion below would pass vacuously.
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
    def test_it_prompts_when_no_voice_is_installed(
        self, plugin, nvda_gui, no_installed_voices, monkeypatch
    ):
        opened = []
        monkeypatch.setattr(plugin, "on_manager", lambda evt: opened.append(evt))
        plugin._perform_voice_check()
        # nvda_gui's gui.messageBox mock answers wx.YES (see conftest.py),
        # which is the branch that reaches on_manager.
        import gui

        assert gui.messageBox.called
        assert len(opened) == 1

    def test_it_stays_quiet_when_a_voice_is_installed(
        self, plugin, one_installed_voice, monkeypatch
    ):
        import gui

        gui.messageBox.reset_mock()
        plugin._perform_voice_check()
        assert not gui.messageBox.called

    def test_it_stays_quiet_once_the_manager_has_been_opened(
        self, plugin, no_installed_voices
    ):
        import gui

        # Not exercising the real on_manager here: DengjenVoiceManagerDialog
        # construction needs synth/network fixtures (see
        # test_voice_manager_dialog.py's espeak_synth/offline) that are
        # irrelevant to what this test targets -- the __voice_manager_shown
        # short-circuit in _perform_voice_check -- and dragging them in would
        # only add flakiness risk for no extra coverage. The flag is set
        # directly here so the test isolates that short-circuit alone.
        setattr(plugin, "_GlobalPlugin__voice_manager_shown", True)
        plugin._perform_voice_check()
        assert not gui.messageBox.called
