"""Real-NVDA end-to-end tests: install the built add-on into a real,
disposable NVDA and drive it exactly as a user would.

Order matters in this file: later tests build on state earlier ones leave
behind (the addon_under_test fixture is session-scoped), same convention as
nvda-addon-testkit's own tests_e2e/test_demo_addon.py.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

if sys.platform == "win32":
    from nvda_testkit.namespaces.addons import AddonState

from .conftest import press_until, voice_manager_state, wait_until

ADDON_NAME = "dengjen_neural_voices"
NO_VOICE_MODAL_TEXT = "no dengjen voice was found"
VOICE_MANAGER_TITLE = "dengjen voice manager"
VOICE_DOWNLOADED_TITLE = "Voice downloaded"


@pytest.mark.fresh_nvda
def test_install_is_two_phase_and_completes_on_restart(nvda, addon_bundle):
    """Owns its own install/remove cycle so the rest of this file can rely
    on addon_under_test staying installed -- same reasoning as
    nvda-addon-testkit's own equivalent test."""
    assert nvda.addons.state(ADDON_NAME) is AddonState.NOT_INSTALLED

    info = nvda.addons.install(addon_bundle)
    assert info.name == ADDON_NAME
    assert nvda.addons.state(ADDON_NAME) is AddonState.PENDING_INSTALL

    nvda.relaunch()
    assert nvda.addons.state(ADDON_NAME) is AddonState.ENABLED
    nvda.should_have_no_errors()

    nvda.addons.remove(ADDON_NAME)
    nvda.relaunch()
    assert nvda.addons.state(ADDON_NAME) is AddonState.NOT_INSTALLED


def test_the_no_voice_modal_appears_and_no_declines_it(nvda, addon_under_test):
    """_perform_voice_check calls _ask_first_run_voice_action, which shows a
    real, blocking wx.MessageDialog 3s after startup when no voice is
    installed (__init__.py:68-106). This is exactly the behavior
    tests_gui/test_global_plugin.py cannot prove, since it monkeypatches
    _ask_first_run_voice_action outright rather than risk a real ShowModal
    hanging the test run."""
    nvda.relaunch()

    # simulate_modal only fires on a window that appears after it starts
    # polling, so arm it before the startup prompt shows, not after hearing it.
    assert nvda.simulate_modal("no", timeout=20)
    nvda.should_hear(NO_VOICE_MODAL_TEXT)
    nvda.wait_until_idle(timeout=15)
    has_voice_manager = voice_manager_state(
        nvda, "any(hasattr(w, 'notebookCtrl') for w in wx.GetTopLevelWindows())"
    )
    assert not has_voice_manager
    nvda.should_have_no_errors()


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
    nvda.restart_harness()
    before = nvda.speech.index()
    nvda.speech.wait_for(NO_VOICE_MODAL_TEXT, timeout=15, since=before)
    nvda.keys.press("o")

    nvda.speech.wait_for(VOICE_MANAGER_TITLE, timeout=10, since=before)

    before = nvda.speech.index()
    press_until(
        nvda,
        "control+tab",
        lambda: (
            voice_manager_state(nvda, "manager and manager.notebookCtrl.GetSelection()")
            == 1
        ),
        description="the notebook to switch to the Download tab",
    )

    nvda.speech.wait_for("retrieving voices list", timeout=10, since=before)
    wait_until(
        lambda: (
            voice_manager_state(
                nvda,
                "(manager and manager.notebookCtrl.GetPage(1)"
                ".language_choice.GetCount()) or 0",
            )
            > 0
        ),
        timeout=30,
        description="the online language list to populate",
    )

    nvda.keys.press("tab")
    nvda.keys.press("downArrow")
    wait_until(
        lambda: (
            voice_manager_state(
                nvda,
                "(manager and manager.notebookCtrl.GetPage(1)"
                ".voices_list.GetItemCount()) or 0",
            )
            > 0
        ),
        timeout=10,
        description="voices for the selected language to list",
    )

    rt_index = voice_manager_state(
        nvda,
        "next("
        "  (i for i, v in enumerate("
        "    manager.notebookCtrl.GetPage(1).voices_list._objects"
        "    if manager else []"
        "  )"
        "  if v.has_rt_variant and v.num_speakers <= 1),"
        "  None"
        ")",
    )
    assert rt_index is not None, (
        "no voice for the first language has a fast (RT) variant"
    )

    nvda.keys.press("tab")
    for _ in range(rt_index):
        nvda.keys.press("downArrow")

    online_key = wait_until(
        lambda: voice_manager_state(
            nvda,
            "(manager and manager.notebookCtrl.GetPage(1)"
            ".voices_list.get_selected().key) or None",
        ),
        timeout=10,
        description="the selected online voice key",
    )

    nvda.keys.press_all("tab", "tab", "tab")
    before = nvda.speech.index()
    nvda.keys.press("space")

    nvda.speech.wait_for(
        "voice downloaded|successfully downloaded", timeout=90, since=before
    )

    press_until(
        nvda,
        "n",
        lambda: (
            voice_manager_state(nvda, "dialog.GetTitle() if dialog else ''")
            != VOICE_DOWNLOADED_TITLE
        ),
        description="the voice-downloaded message box to close",
    )

    if not voice_manager_state(
        nvda, "dialog is not None and hasattr(dialog, 'notebookCtrl')"
    ):
        press_until(
            nvda,
            "alt+tab",
            lambda: voice_manager_state(
                nvda, "dialog is not None and hasattr(dialog, 'notebookCtrl')"
            ),
            description="focus to return to the voice manager dialog",
        )

    nvda.wait_until_idle(timeout=15)

    lang, name, quality = online_key.split("-")
    return f"{lang}-{name}+RT-{quality}"


def test_downloading_the_fast_variant_voice_installs_it(nvda, downloaded_voice_key):
    """Depends on downloaded_voice_key leaving the voice manager dialog open on the Download tab."""

    nvda.wait_until_idle(timeout=15)

    press_until(
        nvda,
        "control+tab",
        lambda: (
            voice_manager_state(nvda, "manager and manager.notebookCtrl.GetSelection()")
            == 0
        ),
        description="the notebook to switch to the Installed tab",
    )

    installed_keys = wait_until(
        lambda: voice_manager_state(
            nvda,
            "[v.key for v in (manager.notebookCtrl.GetPage(0)"
            ".voices_list._objects if manager else [])]",
        ),
        timeout=15,
        description="the Installed tab to list the just-downloaded voice",
    )
    assert downloaded_voice_key in installed_keys
    nvda.should_have_no_errors()


KOKORO_TAB_INDEX = 2
KOKORO_VOICE_KEY = "kokoro-multilingual"
# ~350MB (full-precision model + 54 preset embeddings) over the CI network --
# generous on purpose to tolerate a slow real download.
# Overridable via env for a CI runner with a slower or throttled connection.
KOKORO_INSTALL_TIMEOUT = int(os.environ.get("KOKORO_INSTALL_TIMEOUT_SECONDS", "300"))
KOKORO_CACHE_DIR = (
    Path(
        os.environ.get(
            "DENGJEN_KOKORO_CACHE_DIR", Path.home() / ".cache" / "dengjen-kokoro"
        )
    ).expanduser()
    / KOKORO_VOICE_KEY
)


def _resolve_kokoro_install_dir(nvda) -> Path:
    """The real, on-disk install dir inside the fresh portable's own config,
    read from NVDA itself rather than nvda-addon-testkit's private
    Provisioned.workdir -- mirrors const.py's DENGJEN_KOKORO_VOICES_DIR
    construction without depending on that internal attribute."""
    config_path = nvda.eval("__import__('globalVars').appArgs.configPath")
    return Path(config_path) / "dengjen" / "voices" / "kokoro" / KOKORO_VOICE_KEY


def _refresh_installed_tab_after_out_of_band_install(nvda) -> None:
    """Re-reads the Installed tab, which populates once and would otherwise
    keep its pre-Kokoro list. Only that tab: invalidating the Download tab
    too would make its next visit refetch the online voice list."""
    voice_manager_state(
        nvda,
        "(lambda page: (page.invalidate_cache(), page.populate_list()))"
        "(manager.notebookCtrl.GetPage(0))",
    )


def _selected_tab(nvda):
    return voice_manager_state(nvda, "manager and manager.notebookCtrl.GetSelection()")


def _switch_to_installed_tab(nvda) -> None:
    """A no-op when already there: the Kokoro tab has no enabled control once
    installed, so a stray control+tab through it strands focus on Close."""
    if _selected_tab(nvda) == 0:
        return
    press_until(
        nvda,
        "control+tab",
        lambda: _selected_tab(nvda) == 0,
        description="the notebook to switch to the Installed tab",
    )


def _copy_voice_tree(src: Path, dest: Path) -> None:
    """config.json copied last, same invariant _install() documents in
    kokoro_download.py: it's the only file is_installed() checks, so a copy
    interrupted partway must not leave a directory that looks installed."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("config.json")
    )
    shutil.copy(src / "config.json", dest / "config.json")


@pytest.fixture(scope="session")
def kokoro_installed(nvda_session, downloaded_voice_key):
    """Installs the real Kokoro voice, once per session -- from a warm local
    cache when one exists (seeded by build_addon.yml's "Restore Kokoro voice
    cache" step), otherwise via the real Kokoro tab exactly as before, which
    then warms the cache for "Save Kokoro voice cache" to persist.

    Depends on downloaded_voice_key (not just nvda_session) so the voice
    manager dialog is already open on the Installed tab -- reusing it
    instead of re-deriving how to open it a second time, since the no-voice
    modal that opened it originally only fires when zero voices are
    installed."""
    nvda = nvda_session
    nvda.wait_until_idle(timeout=15)

    install_dir = _resolve_kokoro_install_dir(nvda)

    if (KOKORO_CACHE_DIR / "config.json").exists():
        _copy_voice_tree(KOKORO_CACHE_DIR, install_dir)
        assert (install_dir / "config.json").exists()
        _refresh_installed_tab_after_out_of_band_install(nvda)
        return KOKORO_VOICE_KEY

    press_until(
        nvda,
        "control+tab",
        lambda: (
            voice_manager_state(nvda, "manager and manager.notebookCtrl.GetSelection()")
            == KOKORO_TAB_INDEX
        ),
        attempts=KOKORO_TAB_INDEX + 3,
        description="the notebook to switch to the Kokoro tab",
    )

    # A single blind tab press here landed on the dialog's own Close button
    # (not KokoroVoicesPanel's install_btn) on real CI, closing the whole
    # dialog instead of installing anything -- wx's tab order after a
    # control+tab page switch isn't reliably "one tab into the new page's
    # first control" once other interactions already happened earlier in
    # this file. Verify focus actually lands on install_btn before pressing
    # space, retrying tab presses rather than assuming a fixed count.
    press_until(
        nvda,
        "tab",
        lambda: voice_manager_state(
            nvda,
            "manager is not None and wx.Window.FindFocus() is "
            f"manager.notebookCtrl.GetPage({KOKORO_TAB_INDEX}).install_btn",
        ),
        attempts=5,
        description="focus to reach the Install Kokoro voice button",
    )
    nvda.keys.press("space")

    # Ground truth is the real config.json on disk (via the Kokoro page's
    # own already-live _catalog), not NVDA's speech -- a real CI run has
    # shown NVDA's focus can be stolen by an unrelated window mid-download
    # and never return, even though the install completes normally in the
    # background.
    wait_until(
        lambda: voice_manager_state(
            nvda,
            "manager is not None and "
            f"manager.notebookCtrl.GetPage({KOKORO_TAB_INDEX})._catalog.is_installed()",
        ),
        timeout=KOKORO_INSTALL_TIMEOUT,
        description="the Kokoro voice files to finish installing (config.json on disk)",
    )
    wait_until(
        lambda: (
            voice_manager_state(nvda, "dialog.GetTitle() if dialog else ''")
            == VOICE_DOWNLOADED_TITLE
        ),
        timeout=15,
        description="the voice-downloaded message box to appear",
    )

    press_until(
        nvda,
        "n",
        lambda: (
            voice_manager_state(nvda, "dialog.GetTitle() if dialog else ''")
            != VOICE_DOWNLOADED_TITLE
        ),
        description="the voice-downloaded message box to close",
    )

    if not voice_manager_state(
        nvda, "dialog is not None and hasattr(dialog, 'notebookCtrl')"
    ):
        press_until(
            nvda,
            "alt+tab",
            lambda: voice_manager_state(
                nvda, "dialog is not None and hasattr(dialog, 'notebookCtrl')"
            ),
            description="focus to return to the voice manager dialog",
        )
    nvda.wait_until_idle(timeout=15)

    _copy_voice_tree(install_dir, KOKORO_CACHE_DIR)
    return KOKORO_VOICE_KEY


def test_kokoro_installs_and_lists_alongside_the_piper_voice(
    nvda, kokoro_installed, downloaded_voice_key
):
    _switch_to_installed_tab(nvda)
    installed_keys = wait_until(
        lambda: voice_manager_state(
            nvda,
            "[v.key for v in (manager.notebookCtrl.GetPage(0)"
            ".voices_list._objects if manager else [])]",
        ),
        timeout=15,
        description="the Installed tab to list Kokoro alongside the Piper voice",
    )
    assert kokoro_installed in installed_keys
    assert downloaded_voice_key in installed_keys
    nvda.should_have_no_errors()


def test_kokoro_produces_real_speech(nvda, kokoro_installed):
    nvda.config.set(["speech", "synth"], ADDON_NAME)
    nvda.config.set(["speech", ADDON_NAME, "voice"], kokoro_installed)
    nvda.relaunch()

    with nvda.expecting_speech("dengjen kokoro testkit smoke phrase", within=15):
        nvda.speech.speak("dengjen kokoro testkit smoke phrase")
    nvda.should_have_no_errors()


def test_the_downloaded_voice_produces_real_speech(nvda, downloaded_voice_key):
    nvda.config.set(["speech", "synth"], ADDON_NAME)
    nvda.config.set(["speech", ADDON_NAME, "voice"], downloaded_voice_key)
    nvda.relaunch()

    with nvda.expecting_speech("dengjen testkit smoke phrase", within=15):
        nvda.speech.speak("dengjen testkit smoke phrase")
    nvda.should_have_no_errors()


def test_removal_is_also_two_phase(nvda):
    """Must stay last in this file: uninstalls what addon_under_test set up."""
    nvda.addons.remove(ADDON_NAME)
    assert nvda.addons.state(ADDON_NAME) is AddonState.PENDING_REMOVE
    nvda.relaunch()
    assert nvda.addons.state(ADDON_NAME) is AddonState.NOT_INSTALLED
