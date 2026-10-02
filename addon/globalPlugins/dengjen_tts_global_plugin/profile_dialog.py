# coding: utf-8

# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""
Dialog for managing per-application Dengjen voice profiles.
"""

import os
import sys
from pathlib import Path

import addonHandler
import gui
import synthDriverHandler
import wx
from logHandler import log

addonHandler.initTranslation()

_DIR = os.path.abspath(os.path.dirname(__file__))
_ADDON_ROOT = os.path.abspath(os.path.join(_DIR, os.pardir, os.pardir))
_TTS_MODULE_DIR = os.path.join(_ADDON_ROOT, "synthDrivers")
if _TTS_MODULE_DIR not in sys.path:
    sys.path.insert(0, _TTS_MODULE_DIR)

from dengjen_neural_voices.domain.app_profiles import app_profile_manager
from dengjen_neural_voices.const import DENGJEN_VOICES_DIR, DENGJEN_KOKORO_VOICES_DIR
from .components import SimpleDialog
from .sized_controls import SizedPanel


def _get_installed_voice_ids():
    """Retrieve installed voice IDs safely without requiring gRPC or backend instantiation."""
    synth = synthDriverHandler.getSynth()
    if synth is not None and "dengjen" in synth.name.lower() and hasattr(synth, "availableVoices"):
        return sorted(list(synth.availableVoices.keys()))

    # Fallback: scan disk directories directly
    voice_ids = set()
    for directory in (DENGJEN_VOICES_DIR, DENGJEN_KOKORO_VOICES_DIR):
        p = Path(directory)
        if p.is_dir():
            for sub in p.iterdir():
                if sub.is_dir():
                    clean_name = sub.name.replace("+RT", "")
                    voice_ids.add(clean_name)
    return sorted(list(voice_ids))


class DengjenEditProfileDialog(SimpleDialog):
    """Dialog for creating or editing a single app profile."""

    def __init__(self, parent, exe_name="", profile=None):
        self._exe_name = exe_name
        self._profile = profile or {}
        self._voice_ids = _get_installed_voice_ids()
        super().__init__(
            parent,
            title=_("Edit App Profile"),
        )

    def addControls(self, parent):
        parent.SetSizerType("form")

        wx.StaticText(parent, label=_("Application name (e.g. firefox):"))
        self.exe_ctrl = wx.TextCtrl(parent, value=self._exe_name)
        self.exe_ctrl.SetSizerProps(expand=True)

        wx.StaticText(parent, label=_("Voice:"))
        voice_choices = [""] + self._voice_ids
        self.voice_choice = wx.Choice(parent, choices=voice_choices)
        self.voice_choice.SetSizerProps(expand=True)
        current_voice = self._profile.get("voice", "")
        if current_voice in voice_choices:
            self.voice_choice.SetSelection(voice_choices.index(current_voice))
        else:
            self.voice_choice.SetSelection(0)

        wx.StaticText(parent, label=_("Rate (0-100, blank=default):"))
        rate_val = str(self._profile.get("rate", "")) if self._profile.get("rate") is not None else ""
        self.rate_ctrl = wx.TextCtrl(parent, value=rate_val)
        self.rate_ctrl.SetSizerProps(expand=True)

        wx.StaticText(parent, label=_("Volume (0-100, blank=default):"))
        vol_val = str(self._profile.get("volume", "")) if self._profile.get("volume") is not None else ""
        self.volume_ctrl = wx.TextCtrl(parent, value=vol_val)
        self.volume_ctrl.SetSizerProps(expand=True)

        wx.StaticText(parent, label=_("Pitch (0-100, blank=default):"))
        pitch_val = str(self._profile.get("pitch", "")) if self._profile.get("pitch") is not None else ""
        self.pitch_ctrl = wx.TextCtrl(parent, value=pitch_val)
        self.pitch_ctrl.SetSizerProps(expand=True)

    def getButtons(self, parent):
        btnsizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK, _("OK"))
        ok_btn.SetDefault()
        cancel_btn = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        btnsizer.AddButton(ok_btn)
        btnsizer.AddButton(cancel_btn)
        btnsizer.Realize()
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        return btnsizer

    def _parse_int(self, ctrl):
        val = ctrl.GetValue().strip()
        if not val:
            return None
        try:
            return max(0, min(100, int(val)))
        except ValueError:
            return None

    def _on_ok(self, event):
        exe = self.exe_ctrl.GetValue().strip().lower()
        if not exe:
            gui.messageBox(_("Please enter an application name."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            return
        self._exe_name = exe
        voice_idx = self.voice_choice.GetSelection()
        choices = [""] + self._voice_ids
        voice = choices[voice_idx] if voice_idx >= 0 else ""
        self._profile = {
            "voice": voice or None,
            "rate": self._parse_int(self.rate_ctrl),
            "volume": self._parse_int(self.volume_ctrl),
            "pitch": self._parse_int(self.pitch_ctrl),
        }
        event.Skip()

    def get_result(self):
        return self._exe_name, self._profile


class DengjenAppProfileDialog(SimpleDialog):
    """Main dialog listing all app profiles with Add / Edit / Delete."""

    def __init__(self):
        super().__init__(
            gui.mainFrame,
            title=_("Dengjen App Profiles"),
        )
        self.SetSize((520, 420))
        self.CenterOnScreen()

    def addControls(self, parent):
        parent.SetSizerType("vertical")

        desc = wx.StaticText(
            parent,
            label=_(
                "Configure per-application voice settings.\n"
                "Dengjen will automatically switch to the saved profile\n"
                "when the specified application gains focus."
            ),
        )
        desc.SetSizerProps(expand=True)

        self.list_ctrl = wx.ListCtrl(parent, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, _("Application"), width=160)
        self.list_ctrl.InsertColumn(1, _("Voice"), width=200)
        self.list_ctrl.InsertColumn(2, _("Rate"), width=60)
        self.list_ctrl.SetSizerProps(expand=True, proportion=1)

        btn_panel = SizedPanel(parent, -1)
        btn_panel.SetSizerType("horizontal")
        btn_panel.SetSizerProps(expand=True)

        self.add_btn = wx.Button(btn_panel, label=_("&Add..."))
        self.edit_btn = wx.Button(btn_panel, label=_("&Edit..."))
        self.delete_btn = wx.Button(btn_panel, label=_("&Delete"))

        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit)

        self._refresh_list()

    def getButtons(self, parent):
        btnsizer = wx.StdDialogButtonSizer()
        closeBtn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        btnsizer.AddButton(closeBtn)
        btnsizer.Realize()
        return btnsizer

    def _refresh_list(self):
        self.list_ctrl.DeleteAllItems()
        for exe, profile in app_profile_manager.list_profiles():
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), exe)
            self.list_ctrl.SetItem(idx, 1, profile.get("voice") or "")
            rate = profile.get("rate")
            self.list_ctrl.SetItem(idx, 2, str(rate) if rate is not None else "")

    def _selected_exe(self):
        idx = self.list_ctrl.GetFirstSelected()
        return self.list_ctrl.GetItemText(idx, 0) if idx != -1 else None

    def _on_add(self, event):
        dlg = DengjenEditProfileDialog(self)
        if gui.runScriptModalDialog(dlg) == wx.ID_OK:
            exe, profile = dlg.get_result()
            app_profile_manager.set_profile(exe, **profile)
            self._refresh_list()

    def _on_edit(self, event):
        exe = self._selected_exe()
        if exe is None:
            return
        profile = app_profile_manager.get_profile(exe)
        dlg = DengjenEditProfileDialog(self, exe_name=exe, profile=profile)
        if gui.runScriptModalDialog(dlg) == wx.ID_OK:
            new_exe, new_profile = dlg.get_result()
            if new_exe != exe:
                app_profile_manager.delete_profile(exe)
            app_profile_manager.set_profile(new_exe, **new_profile)
            self._refresh_list()

    def _on_delete(self, event):
        exe = self._selected_exe()
        if exe is None:
            return
        if gui.messageBox(
            _("Delete profile for '{app}'?").format(app=exe),
            _("Confirm"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        ) == wx.YES:
            app_profile_manager.delete_profile(exe)
            self._refresh_list()
