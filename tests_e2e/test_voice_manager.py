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
