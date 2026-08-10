# coding: utf-8
"""Real-NVDA end-to-end tests: install the built add-on into a real,
disposable NVDA and drive it exactly as a user would.

Order matters in this file: later tests build on state earlier ones leave
behind (the addon_under_test fixture is session-scoped), same convention as
nvda-addon-testkit's own tests_e2e/test_demo_addon.py.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform == "win32":
    from nvda_testkit.namespaces.addons import AddonState

from .conftest import voice_manager_state, wait_until

ADDON_NAME = "dengjen_neural_voices"
NO_VOICE_MODAL_TEXT = "no dengjen voice was found"
VOICE_MANAGER_TITLE = "dengjen voice manager"


@pytest.mark.fresh_nvda
def test_install_is_two_phase_and_completes_on_restart(
    nvda, addon_bundle, assert_no_unexpected_errors
):
    """Owns its own install/remove cycle so the rest of this file can rely
    on addon_under_test staying installed -- same reasoning as
    nvda-addon-testkit's own equivalent test."""
    assert nvda.addons.state(ADDON_NAME) is AddonState.NOT_INSTALLED

    info = nvda.addons.install(addon_bundle)
    assert info.name == ADDON_NAME
    assert nvda.addons.state(ADDON_NAME) is AddonState.PENDING_INSTALL

    nvda.restart()
    assert nvda.addons.state(ADDON_NAME) is AddonState.ENABLED
    assert_no_unexpected_errors(nvda)

    nvda.addons.remove(ADDON_NAME)
    nvda.restart()
    assert nvda.addons.state(ADDON_NAME) is AddonState.NOT_INSTALLED


def test_the_no_voice_modal_appears_and_no_declines_it(
    nvda, addon_under_test, assert_no_unexpected_errors
):
    """_perform_voice_check fires a real, blocking gui.messageBox 3s after
    startup when no voice is installed (__init__.py:58-74). This is exactly
    the behavior tests_gui/test_global_plugin.py cannot prove, since it
    mocks gui.messageBox so the call never actually blocks."""
    nvda.restart()  # fresh startup -> _voice_checker fires again

    before = nvda.speech.index()
    nvda.speech.wait_for(NO_VOICE_MODAL_TEXT, timeout=15, since=before)

    nvda.keys.press("n")  # decline

    active_title = voice_manager_state(nvda, "dialog.GetTitle() if dialog else ''")
    assert VOICE_MANAGER_TITLE not in active_title.lower()
    assert_no_unexpected_errors(nvda)


@pytest.fixture(scope="session")
def downloaded_voice_key(nvda_session, addon_under_test):
    """Downloads one real voice via the real dialog, once per session.
    Tests 4 (this) and 5 (real speech) both need a voice actually on disk;
    this fixture is where that happens so speech-focused tests don't also
    have to drive the download UI.

    Depends on nvda_session, not the function-scoped nvda: a session-scoped
    fixture cannot request a narrower-scoped one (pytest ScopeMismatch).
    nvda_session is the same underlying NvdaClient nvda wraps with a
    per-test reset()."""
    nvda = nvda_session
    nvda.restart()  # fresh startup -> the no-voice modal fires again
    before = nvda.speech.index()
    nvda.speech.wait_for(NO_VOICE_MODAL_TEXT, timeout=15, since=before)
    nvda.keys.press("y")  # open the voice manager

    nvda.speech.wait_for(VOICE_MANAGER_TITLE, timeout=10, since=before)
    nvda.keys.press("control+tab")  # Installed tab -> Download tab

    before = nvda.speech.index()
    nvda.speech.wait_for("retrieving voices list", timeout=10, since=before)
    wait_until(
        lambda: voice_manager_state(
            nvda, "dialog.notebookCtrl.GetPage(1).language_choice.GetCount()"
        ) > 0,
        timeout=30,
        description="the online language list to populate",
    )

    nvda.keys.press("downArrow")  # select the first language
    wait_until(
        lambda: voice_manager_state(
            nvda, "dialog.notebookCtrl.GetPage(1).voices_list.GetItemCount()"
        ) > 0,
        timeout=10,
        description="voices for the selected language to list",
    )

    rt_index = voice_manager_state(
        nvda,
        "next("
        "  i for i, v in enumerate(dialog.notebookCtrl.GetPage(1).voices_list._objects)"
        "  if v.has_rt_variant"
        ")",
    )
    assert rt_index is not None, "no voice for the first language has a fast (RT) variant"

    for _ in range(rt_index):
        nvda.keys.press("downArrow")

    voice_key = voice_manager_state(
        nvda, "dialog.notebookCtrl.GetPage(1).voices_list.get_selected().key"
    )

    nvda.keys.press_all("tab", "tab", "tab")  # voices_list -> preview -> std -> rt button
    before = nvda.speech.index()
    nvda.keys.press("space")  # "Download &fast variant"

    nvda.speech.wait_for("voice downloaded|successfully downloaded", timeout=90, since=before)
    nvda.keys.press("n")  # decline the immediate restart offer; Task 5 restarts explicitly

    return voice_key


def test_downloading_the_fast_variant_voice_installs_it(nvda, downloaded_voice_key, assert_no_unexpected_errors):
    # The download's success callback only invalidates the Installed tab's
    # cache (DengjenVoiceManagerDialog._invalidate_pages_voice_cache); it
    # does not repopulate a tab that isn't showing. Switching to it is what
    # triggers onNotebookPageChanged -> populate_list() -> a real refresh
    # from disk, same as a user checking their download landed.
    nvda.keys.press("control+tab")  # Download tab -> Installed tab
    installed_keys = voice_manager_state(
        nvda,
        "[v.key for v in dialog.notebookCtrl.GetPage(0).voices_list._objects]",
    )
    assert downloaded_voice_key in installed_keys
    assert_no_unexpected_errors(nvda)
