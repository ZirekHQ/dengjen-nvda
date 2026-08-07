# coding: utf-8
"""
Construction and event-wiring smoke tests for voice_manager.py against real
wxPython.

Scope is deliberately narrow: that the dialog builds, that every control the
handlers reach for exists, and that each button reaches the handler it is
meant to. A handler bound to the wrong control is invisible to every other
layer -- voice_manager_logic.py's tests prove the decisions are right, not
that they are wired to anything.

Wiring proof rule: never re-Bind a control and never monkeypatch the handler
under test. self.Bind(...) captures the bound method at construction time, so
re-Binding or swapping the handler afterwards only proves Bind/ProcessEvent
work -- that's wxPython's job. Instead fire a real wx.CommandEvent at the
construction-time binding and observe a side effect on a collaborator (a
mocked gui.* call, a mocked downloader class, or a control's own state).

Never call ShowModal(): with no event loop it blocks until the CI job times
out. Dialogs are constructed, asserted against, and destroyed.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)

import wx
from wx.adv import CommandLinkButton
import gui


@pytest.fixture
def voice_manager(gui_plugin_package):
    from dengjen_tts_global_plugin import voice_manager

    return voice_manager


@pytest.fixture
def no_installed_voices(voice_manager, monkeypatch):
    """load_piper_voices_from_nvda_config_dir touches the NVDA config dir;
    pin it to empty so construction never depends on the host machine."""
    monkeypatch.setattr(
        voice_manager.DengjenTextToSpeechSystem,
        "load_piper_voices_from_nvda_config_dir",
        classmethod(lambda cls: iter([])),
    )


@pytest.fixture
def espeak_synth(voice_manager, monkeypatch):
    """A non-dengjen active synth -- the safe default, since a dengjen synth
    would let update_voices_list call synth.terminate()/__init__()."""
    synth = MagicMock()
    synth.name = "espeak"
    synth.voice = "en"
    monkeypatch.setattr(
        voice_manager.synthDriverHandler, "getSynth", lambda: synth
    )
    return synth


@pytest.fixture
def offline(voice_manager, monkeypatch, sync_executor):
    """No network: the Download tab calls get_available_voices on
    construction, via AsyncSnakDialog."""
    monkeypatch.setattr(
        voice_manager.voice_download, "get_available_voices", lambda **kw: []
    )
    monkeypatch.setattr(
        voice_manager.voice_download, "THREAD_POOL_EXECUTOR", sync_executor
    )


@pytest.fixture
def dialog(voice_manager, nvda_gui, no_installed_voices, espeak_synth, offline):
    dlg = voice_manager.DengjenVoiceManagerDialog()
    yield dlg
    dlg.Destroy()


class TestDialogConstruction:
    def test_dialog_builds(self, dialog):
        assert isinstance(dialog, wx.Dialog)

    def test_it_has_two_notebook_pages(self, dialog):
        assert dialog.notebookCtrl.GetPageCount() == 2

    def test_pages_are_labelled_installed_and_download(self, dialog):
        labels = [
            dialog.notebookCtrl.GetPageText(i)
            for i in range(dialog.notebookCtrl.GetPageCount())
        ]
        assert labels == ["Installed", "Download"]

    def test_it_has_a_close_button(self, dialog):
        assert dialog.FindWindowById(wx.ID_CANCEL) is not None


class TestInstalledPanelControls:
    @pytest.fixture
    def panel(self, dialog):
        return dialog.notebookCtrl.GetPage(0)

    @pytest.fixture
    def installed_voice(self, tmp_path):
        """A stand-in for a DengjenTextToSpeechSystem installed-voice record:
        only the attributes the panel's columns and handlers actually touch.
        `location` is a real, empty temp dir -- no MODEL_CARD file inside."""
        return SimpleNamespace(
            key="en_US-amy-medium",
            name="amy",
            variant="medium",
            properties={"quality": "medium"},
            language="en",
            location=tmp_path,
        )

    def test_named_controls_exist(self, panel):
        assert panel.voices_list is not None
        assert panel.model_card_button is not None
        assert panel.remove_voice_button is not None

    def test_buttons_are_disabled_with_no_voices_installed(self, panel):
        assert panel.buttons_panel.IsEnabled() is False

    def test_model_card_with_nothing_selected_does_not_raise(self, panel):
        panel.on_model_card(None)

    def test_model_card_button_reaches_on_model_card(self, panel, installed_voice):
        panel.voices_list.set_objects([installed_voice])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.model_card_button)
        # No MODEL_CARD file at `location` -> the "not found" messageBox path.
        assert gui.messageBox.called

    def test_model_card_button_with_nothing_selected_focuses_first_item(
        self, panel, installed_voice
    ):
        panel.voices_list.set_objects([installed_voice], set_focus=False)
        assert panel.voices_list.GetFocusedItem() == wx.NOT_FOUND
        _fire_button(panel, panel.model_card_button)
        assert panel.voices_list.GetFocusedItem() == 0

    def test_remove_voice_button_reaches_on_remove_voice(
        self, panel, voice_manager, monkeypatch, installed_voice
    ):
        # HAZARD: on_remove_voice calls shutil.rmtree(selected.location) on
        # YES, and nvda_gui's gui.messageBox mock always returns wx.ID_YES.
        # Must stub rmtree before firing, regardless of how disposable
        # `location` looks.
        monkeypatch.setattr(voice_manager.shutil, "rmtree", MagicMock())
        panel.voices_list.set_objects([installed_voice])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.remove_voice_button)
        assert voice_manager.shutil.rmtree.called

    def test_add_voice_button_reaches_on_install_voice_from_tar(self, panel):
        # add_voice_button is a local in InstalledDengjenVoicesPanel.__init__,
        # so it has no attribute on the panel -- find it by type instead.
        add_voice_button = _find_child_of_type(panel, CommandLinkButton)
        _fire_button(panel, add_voice_button)
        assert gui.runScriptModalDialog.called


class TestOnlinePanelControls:
    @pytest.fixture
    def panel(self, dialog):
        return dialog.notebookCtrl.GetPage(1)

    def test_named_controls_exist(self, panel):
        assert panel.language_choice is not None
        assert panel.speaker_choice is not None
        assert panel.preview_btn is not None
        assert panel.download_std_btn is not None
        assert panel.download_rt_btn is not None

    def test_speaker_choice_starts_disabled(self, panel):
        assert panel.speaker_choice.IsEnabled() is False

    def test_buttons_panel_starts_disabled(self, panel):
        assert panel.buttons_panel.IsEnabled() is False

    def test_set_voices_fills_the_language_choice(self, panel, online_voices):
        panel.set_voices(online_voices)
        assert panel.language_choice.GetCount() == 2

    def test_voice_selection_enables_the_matching_download_buttons(
        self, panel, online_voices
    ):
        panel.set_voices(online_voices)
        panel.voices_list.set_objects([online_voices[0]])
        panel.voices_list.set_focused_item(0)
        panel.on_voice_selected(None)
        assert panel.download_std_btn.IsEnabled() is True
        # the fixture's first voice has no RT variant
        assert panel.download_rt_btn.IsEnabled() is False

    def test_preview_button_reaches_on_preview(
        self, panel, voice_manager, monkeypatch, sync_executor, online_voices
    ):
        monkeypatch.setattr(voice_manager.aio, "THREADED_EXECUTOR", sync_executor)
        monkeypatch.setattr(voice_manager, "play_remote_mp3", lambda url: None)
        panel.voices_list.set_objects([online_voices[0]])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.preview_btn)
        # sync_executor + inline CallAfter means the whole cycle has already
        # run by the time ProcessEvent returns, so the label is back to
        # Preview -- observable proof the real binding reached on_preview.
        assert panel._preview_active is False
        assert "Preview" in panel.preview_btn.GetLabel()

    def test_download_std_button_reaches_on_download(
        self, panel, voice_manager, monkeypatch, online_voices
    ):
        # Stub the collaborator rather than letting a real download run: a
        # real PiperVoiceDownloader.download() pops a wx.ProgressDialog and,
        # for this fixture's file-less voice, would mkdir a real directory
        # under DENGJEN_VOICES_DIR on the runner.
        downloader_cls = MagicMock()
        monkeypatch.setattr(voice_manager.voice_download, "PiperVoiceDownloader", downloader_cls)
        panel.voices_list.set_objects([online_voices[0]])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.download_std_btn)
        assert downloader_cls.called
        assert downloader_cls.return_value.download.called

    def test_download_rt_button_reaches_on_download_rt(
        self, panel, voice_manager, monkeypatch, online_voices
    ):
        downloader_cls = MagicMock()
        monkeypatch.setattr(voice_manager.voice_download, "PiperRTVoiceDownloader", downloader_cls)
        panel.voices_list.set_objects([online_voices[0]])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.download_rt_btn)
        assert downloader_cls.called
        assert downloader_cls.return_value.download.called


def _fire_button(window, button):
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    window.ProcessEvent(event)


def _find_child_of_type(window, cls):
    for child in window.GetChildren():
        if isinstance(child, cls):
            return child
    raise AssertionError(f"No child of type {cls!r} found under {window!r}")


@pytest.fixture
def online_voices(gui_plugin_package):
    from dengjen_tts_global_plugin import voice_download

    def language(code, name_english):
        return voice_download.PiperVoiceLanguage(
            code=code,
            family=code.split("_")[0],
            region=code.split("_")[-1],
            name_native=name_english,
            name_english=name_english,
            country_english="Country",
        )

    def voice(key, name, lang, **kwargs):
        return voice_download.PiperVoice(
            key=key,
            name=name,
            quality=voice_download.PiperVoiceQualityLevel.Medium,
            num_speakers=1,
            speaker_id_map={},
            language=lang,
            files=[],
            has_rt_variant=kwargs.pop("has_rt_variant", False),
            standard_variant_installed=False,
            fast_variant_installed=False,
        )

    en = language("en_US", "English")
    de = language("de_DE", "German")
    return [
        voice("en_US-amy-medium", "amy", en),
        voice("de_DE-thorsten-medium", "thorsten", de),
    ]
