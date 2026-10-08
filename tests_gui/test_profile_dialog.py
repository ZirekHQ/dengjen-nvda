# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""
GUI tests for Dengjen app profile dialogs (profile_dialog.py) against real wxPython.
"""

import sys
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)

import gui
import wx
from dengjen_neural_voices.domain.app_profiles import app_profile_manager
from dengjen_tts_global_plugin import profile_dialog
from dengjen_tts_global_plugin.profile_dialog import (
    DengjenAppProfileDialog,
    DengjenEditProfileDialog,
    _get_installed_voice_ids,
)


@pytest.fixture(autouse=True)
def clean_app_profiles(monkeypatch):
    """Ensure app_profile_manager has a clean state for each test."""
    profiles = {}
    monkeypatch.setattr(
        app_profile_manager, "list_profiles", lambda: sorted(profiles.items())
    )
    monkeypatch.setattr(
        app_profile_manager, "get_profile", lambda exe: profiles.get(exe, {})
    )

    def _set_profile(exe, **kwargs):
        profiles[exe] = {k: v for k, v in kwargs.items() if v is not None}

    def _delete_profile(exe):
        profiles.pop(exe, None)

    monkeypatch.setattr(app_profile_manager, "set_profile", _set_profile)
    monkeypatch.setattr(app_profile_manager, "delete_profile", _delete_profile)
    return profiles


class TestGetInstalledVoiceIds:
    def test_returns_voices_from_active_dengjen_synth(self, monkeypatch):
        import synthDriverHandler

        synth = MagicMock()
        synth.name = "dengjen_neural_voices"
        synth.availableVoices = {
            "en_US-libritts-high": MagicMock(),
            "en_US-amy-low": MagicMock(),
        }
        monkeypatch.setattr(synthDriverHandler, "getSynth", lambda: synth)
        assert _get_installed_voice_ids() == ["en_US-amy-low", "en_US-libritts-high"]

    def test_falls_back_to_disk_scan_when_synth_is_not_dengjen(
        self, tmp_path, monkeypatch
    ):
        import synthDriverHandler

        monkeypatch.setattr(synthDriverHandler, "getSynth", lambda: None)
        v_dir = tmp_path / "piper"
        k_dir = tmp_path / "kokoro"
        v_dir.mkdir()
        k_dir.mkdir()
        (v_dir / "voice1+RT").mkdir()
        (k_dir / "voice2").mkdir()

        monkeypatch.setattr(profile_dialog, "DENGJEN_VOICES_DIR", str(v_dir))
        monkeypatch.setattr(profile_dialog, "DENGJEN_KOKORO_VOICES_DIR", str(k_dir))

        assert _get_installed_voice_ids() == ["voice1", "voice2"]


class TestEditProfileDialog:
    def test_dialog_construction_and_defaults(self, nvda_gui):
        dlg = DengjenEditProfileDialog(nvda_gui)
        try:
            assert dlg.exe_ctrl.GetValue() == ""
            assert dlg.rate_ctrl.GetValue() == ""
            assert dlg.volume_ctrl.GetValue() == ""
            assert dlg.pitch_ctrl.GetValue() == ""
            assert dlg.voice_choice.GetSelection() == 0
        finally:
            dlg.Destroy()

    def test_dialog_construction_with_existing_profile(self, nvda_gui, monkeypatch):
        monkeypatch.setattr(
            profile_dialog, "_get_installed_voice_ids", lambda: ["v_test"]
        )
        profile = {"voice": "v_test", "rate": 60, "volume": 80, "pitch": 40}
        dlg = DengjenEditProfileDialog(
            nvda_gui, exe_name="notepad.exe", profile=profile
        )
        try:
            assert dlg.exe_ctrl.GetValue() == "notepad.exe"
            assert dlg.rate_ctrl.GetValue() == "60"
            assert dlg.volume_ctrl.GetValue() == "80"
            assert dlg.pitch_ctrl.GetValue() == "40"
            assert dlg.voice_choice.GetStringSelection() == "v_test"
        finally:
            dlg.Destroy()

    def test_parse_int_handles_various_inputs(self, nvda_gui):
        dlg = DengjenEditProfileDialog(nvda_gui)
        try:
            dlg.rate_ctrl.SetValue("")
            assert dlg._parse_int(dlg.rate_ctrl) is None

            dlg.rate_ctrl.SetValue("  ")
            assert dlg._parse_int(dlg.rate_ctrl) is None

            dlg.rate_ctrl.SetValue("not_a_number")
            assert dlg._parse_int(dlg.rate_ctrl) is None

            dlg.rate_ctrl.SetValue("50")
            assert dlg._parse_int(dlg.rate_ctrl) == 50

            dlg.rate_ctrl.SetValue("-10")
            assert dlg._parse_int(dlg.rate_ctrl) == 0

            dlg.rate_ctrl.SetValue("150")
            assert dlg._parse_int(dlg.rate_ctrl) == 100
        finally:
            dlg.Destroy()

    def test_on_ok_shows_error_when_exe_is_empty(self, nvda_gui):
        dlg = DengjenEditProfileDialog(nvda_gui)
        try:
            dlg.exe_ctrl.SetValue("   ")
            evt = wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_OK)
            dlg._on_ok(evt)
            assert gui.messageBox.called
        finally:
            dlg.Destroy()

    def test_on_ok_populates_profile_and_skips(self, nvda_gui, monkeypatch):
        monkeypatch.setattr(
            profile_dialog, "_get_installed_voice_ids", lambda: ["v_sample"]
        )
        dlg = DengjenEditProfileDialog(nvda_gui)
        try:
            dlg.exe_ctrl.SetValue("App.EXE")
            dlg.voice_choice.SetSelection(1)  # v_sample
            dlg.rate_ctrl.SetValue("75")
            dlg.volume_ctrl.SetValue("90")
            dlg.pitch_ctrl.SetValue("55")

            evt = wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_OK)
            dlg._on_ok(evt)

            exe, result = dlg.get_result()
            assert exe == "app.exe"
            assert result == {
                "voice": "v_sample",
                "rate": 75,
                "volume": 90,
                "pitch": 55,
            }
        finally:
            dlg.Destroy()


class TestAppProfileDialog:
    def test_dialog_construction_and_controls(self, nvda_gui):
        dlg = DengjenAppProfileDialog()
        try:
            assert dlg.list_ctrl.GetColumnCount() == 3
            assert dlg.add_btn.GetLabel() == _("&Add...")
            assert dlg.edit_btn.GetLabel() == _("&Edit...")
            assert dlg.delete_btn.GetLabel() == _("&Delete")
        finally:
            dlg.Destroy()

    def test_refresh_list_populates_existing_profiles(
        self, nvda_gui, clean_app_profiles
    ):
        clean_app_profiles["firefox.exe"] = {"voice": "voice_a", "rate": 65}
        clean_app_profiles["notepad.exe"] = {"voice": "voice_b", "rate": None}

        dlg = DengjenAppProfileDialog()
        try:
            assert dlg.list_ctrl.GetItemCount() == 2
            assert dlg.list_ctrl.GetItemText(0, 0) == "firefox.exe"
            assert dlg.list_ctrl.GetItemText(0, 1) == "voice_a"
            assert dlg.list_ctrl.GetItemText(0, 2) == "65"

            assert dlg.list_ctrl.GetItemText(1, 0) == "notepad.exe"
            assert dlg.list_ctrl.GetItemText(1, 1) == "voice_b"
            assert dlg.list_ctrl.GetItemText(1, 2) == ""
        finally:
            dlg.Destroy()

    def test_selected_exe_helper(self, nvda_gui, clean_app_profiles):
        clean_app_profiles["code.exe"] = {"voice": "voice_c"}
        dlg = DengjenAppProfileDialog()
        try:
            assert dlg._selected_exe() is None
            dlg.list_ctrl.Select(0)
            dlg.list_ctrl.Focus(0)
            assert dlg._selected_exe() == "code.exe"
        finally:
            dlg.Destroy()

    def test_on_add_flow(self, nvda_gui, clean_app_profiles, monkeypatch):
        dlg = DengjenAppProfileDialog()
        try:

            def fake_run_script_modal(child_dlg, callback=None):
                child_dlg.exe_ctrl.SetValue("calc.exe")
                child_dlg.rate_ctrl.SetValue("80")
                child_dlg._on_ok(wx.CommandEvent())
                if callback:
                    callback(wx.ID_OK)

            monkeypatch.setattr(gui, "runScriptModalDialog", fake_run_script_modal)

            dlg._on_add(wx.CommandEvent())
            assert "calc.exe" in clean_app_profiles
            assert clean_app_profiles["calc.exe"]["rate"] == 80
            assert dlg.list_ctrl.GetItemCount() == 1
        finally:
            dlg.Destroy()

    def test_on_edit_no_selection_is_noop(self, nvda_gui):
        dlg = DengjenAppProfileDialog()
        try:
            dlg._on_edit(wx.CommandEvent())
            assert not gui.runScriptModalDialog.called
        finally:
            dlg.Destroy()

    def test_on_edit_updates_profile(self, nvda_gui, clean_app_profiles, monkeypatch):
        clean_app_profiles["terminal.exe"] = {"voice": "voice_old", "rate": 50}
        dlg = DengjenAppProfileDialog()
        try:
            dlg.list_ctrl.Select(0)
            dlg.list_ctrl.Focus(0)

            def fake_run_script_modal(child_dlg, callback=None):
                child_dlg.exe_ctrl.SetValue("new_terminal.exe")
                child_dlg.rate_ctrl.SetValue("95")
                child_dlg._on_ok(wx.CommandEvent())
                if callback:
                    callback(wx.ID_OK)

            monkeypatch.setattr(gui, "runScriptModalDialog", fake_run_script_modal)

            dlg._on_edit(wx.CommandEvent())
            assert "terminal.exe" not in clean_app_profiles
            assert "new_terminal.exe" in clean_app_profiles
            assert clean_app_profiles["new_terminal.exe"]["rate"] == 95
        finally:
            dlg.Destroy()

    def test_on_delete_confirmed(self, nvda_gui, clean_app_profiles, monkeypatch):
        clean_app_profiles["slack.exe"] = {"voice": "voice_s"}
        dlg = DengjenAppProfileDialog()
        try:
            dlg.list_ctrl.Select(0)
            dlg.list_ctrl.Focus(0)

            monkeypatch.setattr(gui, "messageBox", MagicMock(return_value=wx.YES))

            dlg._on_delete(wx.CommandEvent())
            assert "slack.exe" not in clean_app_profiles
            assert dlg.list_ctrl.GetItemCount() == 0
        finally:
            dlg.Destroy()

    def test_on_delete_cancelled(self, nvda_gui, clean_app_profiles, monkeypatch):
        clean_app_profiles["slack.exe"] = {"voice": "voice_s"}
        dlg = DengjenAppProfileDialog()
        try:
            dlg.list_ctrl.Select(0)
            dlg.list_ctrl.Focus(0)

            monkeypatch.setattr(gui, "messageBox", MagicMock(return_value=wx.NO))

            dlg._on_delete(wx.CommandEvent())
            assert "slack.exe" in clean_app_profiles
            assert dlg.list_ctrl.GetItemCount() == 1
        finally:
            dlg.Destroy()

    def test_on_delete_with_no_selection_is_noop(self, nvda_gui):
        dlg = DengjenAppProfileDialog()
        try:
            dlg._on_delete(wx.CommandEvent())
            assert not gui.messageBox.called
        finally:
            dlg.Destroy()
