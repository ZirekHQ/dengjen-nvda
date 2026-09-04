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

import dataclasses
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

if sys.platform != "win32":
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)

import gui
import wx
from wx.adv import CommandLinkButton


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
        classmethod(lambda cls, backend: iter([])),
    )


@pytest.fixture
def espeak_synth(voice_manager, monkeypatch):
    """A non-dengjen active synth -- the safe default, since a dengjen synth
    would let update_voices_list call synth.terminate()/__init__()."""
    synth = MagicMock()
    synth.name = "espeak"
    synth.voice = "en"
    monkeypatch.setattr(voice_manager.synthDriverHandler, "getSynth", lambda: synth)
    return synth


@pytest.fixture
def offline(voice_manager, monkeypatch, sync_executor):
    """No network: patches the Download tab's get_available_voices call and
    its executor. Only page 0 populates at dialog construction, so these
    patches matter when a test switches to page 1 (see
    TestNotebookPageChanged), not at construction time."""
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
        
        
        
        
        assert gui.messageBox.called
        assert gui.messageBox.call_args.args[1] == "Not found"

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
        
        
        
        
        monkeypatch.setattr(voice_manager.shutil, "rmtree", MagicMock())
        panel.voices_list.set_objects([installed_voice])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.remove_voice_button)
        assert voice_manager.shutil.rmtree.called

    def test_add_voice_button_reaches_on_install_voice_from_tar(self, panel):
        
        
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
        
        
        
        
        assert panel.speaker_choice.IsThisEnabled() is False

    def test_buttons_panel_starts_disabled(self, panel):
        assert panel.buttons_panel.IsEnabled() is False

    def test_set_voices_fills_the_language_choice(self, panel, online_voices):
        panel.set_voices(online_voices)
        assert panel.language_choice.GetCount() == 2

    @pytest.mark.parametrize(
        "standard_variant_installed, expected_std_enabled",
        [(False, True), (True, False)],
    )
    def test_voice_selection_enables_the_matching_download_buttons(
        self,
        panel,
        online_voices,
        standard_variant_installed,
        expected_std_enabled,
    ):
        voice = dataclasses.replace(
            online_voices[0], standard_variant_installed=standard_variant_installed
        )
        panel.set_voices(online_voices)
        panel.voices_list.set_objects([voice])
        panel.voices_list.set_focused_item(0)
        _fire_list_item_selected(panel, panel.voices_list, 0)
        
        
        
        
        
        
        assert panel.download_std_btn.IsThisEnabled() is expected_std_enabled
        
        assert panel.download_rt_btn.IsThisEnabled() is False

    def test_language_selection_populates_voices_and_enables_buttons(
        self, panel, online_voices
    ):
        panel.set_voices(online_voices)
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, panel.language_choice.GetId())
        event.SetEventObject(panel.language_choice)
        event.SetInt(0)  
        panel.ProcessEvent(event)
        assert panel.voices_list.ItemCount == 1
        assert panel.buttons_panel.IsEnabled() is True

    def test_refresh_button_forces_an_online_lookup(
        self, panel, voice_manager, monkeypatch, sync_executor
    ):
        calls = []

        def fake_get_available_voices(**kwargs):
            calls.append(kwargs)
            return []

        monkeypatch.setattr(
            voice_manager.voice_download,
            "get_available_voices",
            fake_get_available_voices,
        )
        monkeypatch.setattr(
            voice_manager.voice_download, "THREAD_POOL_EXECUTOR", sync_executor
        )
        
        
        refresh_btn = _find_child_of_type(panel, wx.Button)
        _fire_button(panel, refresh_btn)
        assert calls == [{"force_online": True}]

    def test_the_wait_toast_it_raises_can_be_dismissed(
        self, panel, voice_manager, monkeypatch
    ):
        
        
        
        
        captured = {}
        monkeypatch.setattr(
            voice_manager, "AsyncSnakDialog", lambda **kwargs: captured.update(kwargs)
        )
        panel.populate_list(force_online=True)
        assert captured["dismiss_callback"]() is True

    def test_preview_button_reaches_on_preview(
        self, panel, voice_manager, monkeypatch, sync_executor, online_voices
    ):
        monkeypatch.setattr(voice_manager.aio.ENGINE, "executor", sync_executor)
        calls = []
        monkeypatch.setattr(voice_manager, "play_remote_mp3", calls.append)
        selected_voice = online_voices[0]
        panel.voices_list.set_objects([selected_voice])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.preview_btn)
        
        
        
        assert calls == [selected_voice.get_preview_url(speaker_idx=0)]
        
        
        
        assert panel._preview_active is False
        assert "Preview" in panel.preview_btn.GetLabel()

    def test_preview_button_resets_state_when_the_engine_is_shut_down(
        self, panel, voice_manager, monkeypatch, online_voices
    ):
        
        
        
        class _RejectingExecutor:
            def submit(self, fn, *args, **kwargs):
                raise RuntimeError("executor is shut down")

        monkeypatch.setattr(voice_manager.aio.ENGINE, "executor", _RejectingExecutor())
        calls = []
        monkeypatch.setattr(voice_manager, "play_remote_mp3", calls.append)
        selected_voice = online_voices[0]
        panel.voices_list.set_objects([selected_voice])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.preview_btn)
        assert calls == []
        assert panel._preview_active is False
        assert "Preview" in panel.preview_btn.GetLabel()

    def test_download_std_button_reaches_on_download(
        self, panel, voice_manager, monkeypatch, online_voices
    ):
        
        
        
        
        downloader_cls = MagicMock()
        monkeypatch.setattr(
            voice_manager.voice_download, "PiperVoiceDownloader", downloader_cls
        )
        panel.voices_list.set_objects([online_voices[0]])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.download_std_btn)
        assert downloader_cls.called
        assert downloader_cls.return_value.download.called

    def test_download_rt_button_reaches_on_download_rt(
        self, panel, voice_manager, monkeypatch, online_voices
    ):
        downloader_cls = MagicMock()
        monkeypatch.setattr(
            voice_manager.voice_download, "PiperRTVoiceDownloader", downloader_cls
        )
        panel.voices_list.set_objects([online_voices[0]])
        panel.voices_list.set_focused_item(0)
        _fire_button(panel, panel.download_rt_btn)
        assert downloader_cls.called
        assert downloader_cls.return_value.download.called


class TestKeyboardAccess:
    """Nothing else in this tree touches the keyboard: ProcessEvent dispatches
    straight at the binding, so it fires a handler whether or not a user could
    ever have reached the control (#97)."""

    def test_every_button_carries_an_access_key(self, dialog):
        
        
        
        buttons = list(_buttons(dialog))
        
        assert len(buttons) >= 9
        assert [
            
            
            button.GetLabel().splitlines()[0]
            for button in buttons
            if _access_key(button) is None
        ] == []

    @pytest.mark.parametrize("page", [0, 1])
    def test_access_keys_do_not_collide_on_a_page(self, dialog, page):
        
        
        
        hidden = _access_keys(dialog.notebookCtrl.GetPage(1 - page))
        visible = _access_keys(dialog)
        for key in hidden:
            visible.remove(key)
        
        assert len(visible) >= 3
        assert len(visible) == len(set(visible)), sorted(visible)

    @pytest.mark.parametrize("page", [0, 1])
    def test_the_voices_list_is_reachable_by_tab(self, dialog, page):
        
        
        panel = dialog.notebookCtrl.GetPage(page)
        assert _reachable_by_tab(panel.voices_list) is True

    def test_the_close_button_is_reachable_by_tab(self, dialog):
        assert _reachable_by_tab(dialog.FindWindowById(wx.ID_CANCEL)) is True

    def test_a_disabled_button_is_not_reachable_by_tab(self, dialog):
        
        
        panel = dialog.notebookCtrl.GetPage(1)
        assert panel.buttons_panel.IsEnabled() is False
        assert _reachable_by_tab(panel.download_std_btn) is False

    def test_the_installed_pages_controls_all_precede_the_close_button(self, dialog):
        panel = dialog.notebookCtrl.GetPage(0)
        
        
        
        panel.buttons_panel.Enable()
        order = _tab_order_from(panel.voices_list)
        close = dialog.FindWindowById(wx.ID_CANCEL)
        assert close.GetId() in order
        assert order[: order.index(close.GetId()) + 1] == _ids(
            panel.voices_list,
            panel.model_card_button,
            panel.remove_voice_button,
            _find_child_of_type(panel, CommandLinkButton),
            close,
        )

    def test_the_download_pages_controls_all_precede_the_close_button(self, dialog):
        
        
        dialog.notebookCtrl.SetSelection(1)
        panel = dialog.notebookCtrl.GetPage(1)
        panel.buttons_panel.Enable()
        order = _tab_order_from(panel.language_choice)
        close = dialog.FindWindowById(wx.ID_CANCEL)
        assert close.GetId() in order
        assert order[: order.index(close.GetId()) + 1] == _ids(
            panel.language_choice,
            panel.voices_list,
            panel.preview_btn,
            panel.download_std_btn,
            panel.download_rt_btn,
            _find_child_of_type(panel, wx.Button),  
            close,
        )
        
        
        
        assert panel.speaker_choice.GetId() not in order


class TestNotebookPageChanged:
    def test_switching_to_the_download_tab_reaches_its_populate_list(
        self, dialog, voice_manager, monkeypatch, sync_executor, online_voices
    ):
        calls = []

        def fake_get_available_voices(**kwargs):
            calls.append(kwargs)
            return online_voices

        monkeypatch.setattr(
            voice_manager.voice_download,
            "get_available_voices",
            fake_get_available_voices,
        )
        monkeypatch.setattr(
            voice_manager.voice_download, "THREAD_POOL_EXECUTOR", sync_executor
        )
        online_panel = dialog.notebookCtrl.GetPage(1)
        
        
        
        dialog.notebookCtrl.SetSelection(1)
        assert calls == [{"force_online": False}]
        assert online_panel.language_choice.GetCount() == 2


def _ids(*windows):
    return [window.GetId() for window in windows]


def _tab_order_from(control, limit=15):
    """The ids of the windows Tab visits from `control`, starting with it.

    Navigate() raises the same wxNavigationKeyEvent a Tab press does, and it is
    the only way to get the order here: wx.UIActionSimulator exists on the
    runner but its keystrokes land nowhere, the job having no foreground
    session. Walking off the end of the page and into the notebook is an
    artefact of that -- entering a page from the tab strip is native handling a
    synthetic event never reaches -- so callers slice at the Close button (#97).

    Ids rather than the windows themselves: for a control the add-on keeps no
    Python reference to, wx builds a fresh wrapper per lookup, so the Close
    button FindFocus() returns is never the object FindWindowById() does.
    """
    control.SetFocus()
    order = []
    while len(order) < limit:
        current = wx.Window.FindFocus()
        if current is None or current.GetId() in order:
            break
        order.append(current.GetId())
        current.Navigate()
    return order


def _reachable_by_tab(window):
    
    
    
    
    return window.AcceptsFocusFromKeyboard() and window.IsEnabled()


def _buttons(window):
    for child in window.GetChildren():
        if isinstance(child, wx.Button):  
            yield child
        else:
            yield from _buttons(child)


def _access_key(button):
    
    match = re.search(r"&(\w)", button.GetLabel().replace("&&", ""))
    return match.group(1).lower() if match else None


def _access_keys(window):
    return [key for key in map(_access_key, _buttons(window)) if key]


def _fire_button(window, button):
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    window.ProcessEvent(event)


def _fire_list_item_selected(window, list_ctrl, index):
    event = wx.ListEvent(wx.EVT_LIST_ITEM_SELECTED.typeId, list_ctrl.GetId())
    event.SetEventObject(list_ctrl)
    event.SetIndex(index)
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
