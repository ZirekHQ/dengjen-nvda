# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

import os
import sys

import addonHandler
import core
import globalPluginHandler
import gui
import languageHandler
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
    from dengjen_neural_voices._config import DengjenConfig
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

from . import download_infra, feedback, language_offer_logic, voice_download
from .voice_manager import DengjenVoiceManagerDialog, install_voice_from_local_file


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__voice_manager_shown = False
        self._voice_check_timer = None
        self._voice_checker = self._schedule_voice_check
        core.postNvdaStartup.register(self._voice_checker)
        self.itemHandle = gui.mainFrame.sysTrayIcon.menu.Append(
            wx.ID_ANY,
            _("Dengjen &voice manager..."),
            _("Open the voice manager to preview, install or download dengjen voices"),
        )
        gui.mainFrame.sysTrayIcon.menu.Bind(
            wx.EVT_MENU, self.on_manager, self.itemHandle
        )
        self.feedbackMenuHandle = self._build_feedback_submenu()

    def _build_feedback_submenu(self):
        feedback_menu = wx.Menu()
        bug_item = feedback_menu.Append(
            wx.ID_ANY,
            _("Report a &bug..."),
            _("Open a pre-filled bug report for this add-on in your browser"),
        )
        feature_item = feedback_menu.Append(
            wx.ID_ANY,
            _("Request a &feature..."),
            _("Open a pre-filled feature request for this add-on in your browser"),
        )
        gui.mainFrame.sysTrayIcon.menu.Bind(wx.EVT_MENU, self.on_report_bug, bug_item)
        gui.mainFrame.sysTrayIcon.menu.Bind(
            wx.EVT_MENU, self.on_request_feature, feature_item
        )
        return gui.mainFrame.sysTrayIcon.menu.AppendSubMenu(
            feedback_menu,
            _("Send &feedback"),
            _("Report a bug or request a feature for this add-on"),
        )

    def on_manager(self, event, initial_language=None):
        manager_dialog = DengjenVoiceManagerDialog(initial_language=initial_language)
        gui.runScriptModalDialog(manager_dialog)
        self.__voice_manager_shown = True

    def on_report_bug(self, event):
        feedback.open_bug_report()

    def on_request_feature(self, event):
        feedback.open_feature_request()

    def _schedule_voice_check(self):
        self._voice_check_timer = wx.CallLater(3000, self._perform_voice_check)

    def _perform_voice_check(self):
        if self.__voice_manager_shown:
            return
        voices = list(
            DengjenTextToSpeechSystem.load_all_voices_from_nvda_config_dir(
                DengjenGrpcBackend()
            )
        )
        if voices:
            self._offer_language_voice(voices)
        else:
            self._ask_first_run_voice_action()

    def _offer_language_voice(self, installed):
        future = download_infra.THREAD_POOL_EXECUTOR.submit(
            voice_download.get_local_catalog
        )
        future.add_done_callback(
            lambda f: wx.CallAfter(self._on_offer_catalog_read, installed, f)
        )

    def _on_offer_catalog_read(self, installed, future):
        try:
            catalog = future.result()
        except Exception:
            log.debug("Could not read the voice catalog for the offer", exc_info=True)
            return
        declined = {
            family
            for family, entry in DengjenConfig.setdefault("language_offer", {}).items()
            if entry["declined"]
        }
        family = language_offer_logic.language_to_offer(
            languageHandler.getLanguage(), installed, catalog, declined
        )
        if family:
            self._ask_language_voice_action(family)

    def _ask_language_voice_action(self, family):
        """Yes/No/Cancel maps to open-manager/don't-ask-again/not-now, so
        Escape defers the offer instead of silencing it for good."""
        dlg = wx.MessageDialog(
            gui.mainFrame,
            _(
                "No installed Dengjen voice matches NVDA's language, but one is "
                "available to download."
            ),
            _("Dengjen Neural Voices"),
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION,
        )
        dlg.SetYesNoCancelLabels(
            _("&Open voice manager"), _("&Don't ask again"), _("Not &now")
        )
        gui.runScriptModalDialog(
            dlg, lambda retval: self._on_language_voice_action_chosen(family, retval)
        )

    def _on_language_voice_action_chosen(self, family, retval):
        if retval == wx.ID_YES:
            self.on_manager(None, initial_language=family)
        elif retval == wx.ID_NO:
            DengjenConfig["language_offer"][family] = {"declined": True}

    def _ask_first_run_voice_action(self):
        """Yes/No/Cancel maps to open-manager/install-local/not-now. A plain
        wx.MessageDialog, not gui.messageBox, since the latter has no way to
        relabel its buttons for a three-way choice. Shown via
        runScriptModalDialog, not ShowModal(), since this runs from the
        startup path and must not block it; runScriptModalDialog also owns
        Destroy(), so this doesn't call it."""
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
        gui.runScriptModalDialog(dlg, self._on_first_run_voice_action_chosen)

    def _on_first_run_voice_action_chosen(self, retval):
        action = {wx.ID_YES: "manager", wx.ID_NO: "local_file"}.get(retval)
        if action == "manager":
            self.on_manager(None)
        elif action == "local_file":
            install_voice_from_local_file(
                on_installed=self._on_first_run_voice_installed
            )

    def _on_first_run_voice_installed(self, voice_key):
        # SynthDriver.voices is a snapshot taken at construction time, so the
        # just-installed voice stays invisible until the driver rebuilds it.
        synth = synthDriverHandler.getSynth()
        if "dengjen" in synth.name.lower():
            synth.terminate()
            synth.__init__()

    def terminate(self):
        try:
            core.postNvdaStartup.unregister(self._voice_checker)
        except Exception:
            log.debug(
                "Failed to unregister the post-startup voice check", exc_info=True
            )
        if self._voice_check_timer is not None and self._voice_check_timer.IsRunning():
            self._voice_check_timer.Stop()
        try:
            gui.mainFrame.sysTrayIcon.menu.DestroyItem(self.itemHandle)
        except Exception:
            log.debug("Failed to remove the Dengjen menu item", exc_info=True)
        try:
            gui.mainFrame.sysTrayIcon.menu.DestroyItem(self.feedbackMenuHandle)
        except Exception:
            log.debug("Failed to remove the Dengjen feedback menu", exc_info=True)
