# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

import os
import sys

import addonHandler
import core
import globalPluginHandler
import gui
import synthDriverHandler
import wx
from logHandler import log

addonHandler.initTranslation()


_DIR = os.path.abspath(os.path.dirname(__file__))
_ADDON_ROOT = os.path.abspath(os.path.join(_DIR, os.pardir, os.pardir))
_TTS_MODULE_DIR = os.path.join(_ADDON_ROOT, "synthDrivers")
sys.path.insert(0, _TTS_MODULE_DIR)
try:
    from dengjen_neural_voices import (
        DENGJEN_VOICES_DIR,
        DengjenTextToSpeechSystem,
        aio,
        helpers,
        voice_migration,
    )
    from dengjen_neural_voices.adapters.dengjen_grpc import DengjenGrpcBackend
finally:
    sys.path.remove(_TTS_MODULE_DIR)
del _DIR, _ADDON_ROOT, _TTS_MODULE_DIR


__all__ = [
    "DENGJEN_VOICES_DIR",
    "DengjenGrpcBackend",
    "DengjenTextToSpeechSystem",
    "aio",
    "helpers",
    "voice_migration",
]

from .voice_manager import DengjenVoiceManagerDialog, install_voice_from_local_file


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__voice_manager_shown = False
        self._voice_checker = lambda: wx.CallLater(3000, self._perform_voice_check)
        core.postNvdaStartup.register(self._voice_checker)
        self.itemHandle = gui.mainFrame.sysTrayIcon.menu.Append(
            wx.ID_ANY,
            _("Dengjen &voice manager..."),
            _("Open the voice manager to preview, install or download dengjen voices"),
        )
        gui.mainFrame.sysTrayIcon.menu.Bind(
            wx.EVT_MENU, self.on_manager, self.itemHandle
        )

    def on_manager(self, event):
        manager_dialog = DengjenVoiceManagerDialog()
        gui.runScriptModalDialog(manager_dialog)
        self.__voice_manager_shown = True

    def _perform_voice_check(self):
        if self.__voice_manager_shown:
            return
        if any(
            DengjenTextToSpeechSystem.load_all_voices_from_nvda_config_dir(
                DengjenGrpcBackend()
            )
        ):
            return
        action = self._ask_first_run_voice_action()
        if action == "manager":
            self.on_manager(None)
        elif action == "local_file":
            install_voice_from_local_file(
                on_installed=self._on_first_run_voice_installed
            )

    def _ask_first_run_voice_action(self):
        """Yes/No/Cancel maps to open-manager/install-local/not-now. A plain
        wx.MessageDialog, not gui.messageBox, since the latter has no way to
        relabel its buttons for a three-way choice."""
        dlg = wx.MessageDialog(
            gui.mainFrame,
            _(
                "No Dengjen voice was found.\n"
                "You can download a voice online, or install one from a "
                "local archive if you already have one."
            ),
            _("Dengjen Neural Voices"),
            wx.YES_NO | wx.CANCEL | wx.ICON_WARNING,
        )
        dlg.SetYesNoCancelLabels(
            _("&Open voice manager"), _("&Install from local file"), _("Not &now")
        )
        try:
            retval = dlg.ShowModal()
        finally:
            dlg.Destroy()
        return {wx.ID_YES: "manager", wx.ID_NO: "local_file"}.get(retval)

    def _on_first_run_voice_installed(self, voice_key):
        # SynthDriver.voices is a snapshot taken at construction time, so the
        # just-installed voice stays invisible until the driver rebuilds it.
        synth = synthDriverHandler.getSynth()
        if "dengjen" in synth.name.lower():
            synth.terminate()
            synth.__init__()

    def terminate(self):
        try:
            gui.mainFrame.sysTrayIcon.menu.DestroyItem(self.itemHandle)
        except Exception:
            log.debug("Failed to remove the Dengjen menu item", exc_info=True)
