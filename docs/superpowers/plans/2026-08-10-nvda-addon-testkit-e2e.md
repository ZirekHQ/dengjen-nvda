# Real-NVDA e2e tests via nvda-addon-testkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `tests_e2e/` suite that installs the built add-on into a real, disposable NVDA (via the `nvda-addon-testkit` PyPI package) and exercises the full real pipeline: install → real startup no-voice modal → real Hugging Face voice download → real synthesized speech → teardown.

**Architecture:** `nvda-addon-testkit` is a separate, already-published pytest plugin that provisions a portable NVDA and exposes a `nvda` fixture with namespaces (`speech`, `log`, `keys`, `config`, `addons`). This repo only *consumes* it: a new `tests_e2e/` tree (Windows-only, self-skipping elsewhere, same pattern as the existing `tests_gui/`), a new minimal `pyproject.toml` holding the plugin's `[tool.nvda-testkit]` config (this repo has no `pyproject.toml` today — pytest is configured via `pytest.ini`), and a new CI job.

**Tech Stack:** pytest, `nvda-addon-testkit` (PyPI), GitHub Actions (`windows-2025` runner), the existing `scons` addon build.

## Global Constraints

- This repo's dev environment is Linux; `nvda-addon-testkit`'s real-NVDA mode is Windows-only. **None of the `tests_e2e/` tests are runnable locally.** Every task that adds or changes a test in `tests_e2e/test_voice_manager.py` is verified by pushing and reading the `e2e` GitHub Actions job's output — not by running pytest locally. Tasks that touch only `conftest.py`, config files, or the workflow YAML *do* have a local verification step (collection, or YAML parsing).
- `tests_e2e/` must stay out of the default `pytest` run and out of every other suite's collection, exactly like `tests_gui/` and `tests_contract/` already do: `pytest.ini`'s `testpaths = tests` already excludes it; `tests_e2e/conftest.py` additionally needs its own `collect_ignore_glob` guard.
- No keyboard gesture is bound in this add-on; the only way into the voice manager dialog without `nvda.eval()` is the real startup "no voice installed" modal (`_perform_voice_check` in `addon/globalPlugins/dengjen_tts_global_plugin/__init__.py:58-74`), which fires via `wx.CallLater(3000, ...)` after `postNvdaStartup`.
- `nvda.eval()` is opt-in (`allow-eval = true` in `pyproject.toml`, or `--nvda-allow-eval`) and runs arbitrary code inside the NVDA process. Use it **only as a read-only synchronization/assertion oracle** (waiting for async wx state, reading back which voice a selection landed on) — never to drive controls. Driving controls goes through `nvda.keys`, because proving real keyboard reachability against a real NVDA is the entire point of this suite; `tests_gui/test_voice_manager_dialog.py` already proves the same reachability against a stub, so an eval-driven test here would just duplicate that at higher cost.
- `nvda-addon-testkit`'s namespaces (`speech`, `log`, `braille`, `keys`, `config`, `addons`) have no generic "poll a UI control" primitive. Where synchronization is needed and there's no natural NVDA speech/log event to wait on (e.g., a background-thread-filled `wx.Choice` that never had focus), poll via `nvda.eval()` in a local `wait_until()` helper (Task 2) rather than fixed `time.sleep()`.
- Message boxes in this add-on are plain `wx.MessageDialog(..., wx.YES_NO)`. On Windows these respond to the `y` / `n` mnemonic keys directly (standard `MessageBox()` API behavior) — use `nvda.keys.press("y")` / `nvda.keys.press("n")` to answer them, not `"enter"` (which would hit whichever button has default focus, which is not asserted anywhere).
- The built add-on lands at the repo root as `dengjen_neural_voices-<version>.nvda-addon` (from `scons`, per `sconstruct:83`), matching the existing `build_addon.yml` artifact glob `./*.nvda-addon`.

---

### Task 1: `nvda-addon-testkit` dependency and config

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-test-e2e.txt`

**Interfaces:**
- Produces: `[tool.nvda-testkit]` config that `nvda_testkit.settings.load_settings()` reads from `pyproject.toml` at the repo root; `requirements-test-e2e.txt` for `pip install -r`, following the existing `requirements-test-gui.txt` pattern (a separate file installed only on the Windows leg).

- [ ] **Step 1: Find the current published version of `nvda-addon-testkit` on PyPI**

Run: `pip index versions nvda-addon-testkit 2>&1 | head -5`

(If that's unavailable in this environment, check https://pypi.org/project/nvda-addon-testkit/#history directly.) Note the latest stable version number — you'll pin to it in Step 2. Don't guess; the local dev checkout of the kit is mid-development past its last tag (`0.1.dev36+...`), which is *not* what's published.

- [ ] **Step 2: Write `requirements-test-e2e.txt`**

```
# nvda-addon-testkit for the real-NVDA e2e layer (Windows leg only).
#
# Installs a disposable portable NVDA, installs the built .nvda-addon into
# it, and drives it via pytest. See tests_e2e/conftest.py for why this tree
# is kept out of every other suite's collection.
nvda-addon-testkit==<version from Step 1>
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[tool.nvda-testkit]
addon-bundle = "dengjen_neural_voices-*.nvda-addon"
nvda-channel = "stable"
allow-eval = true
```

- [ ] **Step 4: Verify locally**

This step *is* runnable on Linux — `nvda-testkit doctor` only fails hard on things that don't need Windows (a missing spy bundle, a channel it can't resolve over the network); it merely warns about Windows for the parts that need it.

```bash
python -m venv /tmp/e2e-check && /tmp/e2e-check/bin/pip install -r requirements-test-e2e.txt
/tmp/e2e-check/bin/nvda-testkit doctor
```

Expected: exits 0, prints `OK`, and shows a `! Driving a real NVDA needs Windows...` warning (not a failure) since we're on Linux.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements-test-e2e.txt
git commit -m "test: add nvda-addon-testkit dependency and config for real-NVDA e2e"
```

---

### Task 2: `tests_e2e/conftest.py` scaffolding

**Files:**
- Create: `tests_e2e/__init__.py` (empty, matching `tests_gui/__init__.py`)
- Create: `tests_e2e/conftest.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first content file).
- Produces:
  - `RUNNER_ENVIRONMENT_ERRORS: tuple[str, ...]` and `check_no_unexpected_errors(client, *, since: int = 0) -> None` — module-level, importable by test files.
  - `assert_no_unexpected_errors` fixture — a callable fixture wrapping `check_no_unexpected_errors`, used as `assert_no_unexpected_errors(nvda)`.
  - `wait_until(predicate: Callable[[], Any], *, timeout: float, interval: float = 0.5, description: str) -> Any` — module-level, importable by test files. Returns the first truthy value `predicate()` produces; raises `AssertionError` naming `description` and the last value seen on timeout.
  - `voice_manager_state(nvda, expr: str) -> Any` — module-level, importable by test files. Evaluates `expr` inside NVDA with `dialog` bound to the currently active top-level window (`wx.GetActiveWindow()`) and `wx` imported; returns the JSON-safe result. Raises `AssertionError` if no window is active.

- [ ] **Step 1: Write `tests_e2e/__init__.py`**

Empty file (matches `tests_gui/__init__.py`).

- [ ] **Step 2: Write `tests_e2e/conftest.py`**

```python
# coding: utf-8
"""conftest.py for the real-NVDA e2e layer.

Deliberately not part of tests/ or tests_gui/: this tree needs a real NVDA
process (nvda-addon-testkit's `nvda` fixture), which only exists on Windows
and is nothing like either of those trees' stubs. pytest.ini's
testpaths=tests keeps it out of a bare `pytest`; collect_ignore_glob below
keeps it out of collection entirely on non-Windows, same pattern as
tests_gui/conftest.py. Run it with `pytest tests_e2e/`.
"""

from __future__ import annotations

import re
import sys
import time
import warnings
from typing import Any, Callable

import pytest

collect_ignore_glob = [] if sys.platform == "win32" else ["test_*.py"]

#: A headless GitHub Windows runner has no audio endpoint, no braille
#: display and no interactive desktop, so NVDA logs ERROR while
#: initialising those on every startup. Those errors are the runner, not
#: the add-on under test -- asserting on them would make the first CI run
#: a false alarm. Same allowlist shape as nvda-addon-testkit's own
#: tests_e2e/conftest.py, which hit the same runner noise first.
RUNNER_ENVIRONMENT_ERRORS = (
    r"nvwave|WASAPI|audio (?:device|output|session|endpoint)",
    r"synthDriver|synthesi[sz]|espeak|oneCore|SAPI",
    r"braille ?display|brailleDisplayDriver|brailleInput",
    r"UIAHandler|IAccessible|interactive desktop|desktop object",
)

_RUNNER_ENVIRONMENT = re.compile("|".join(RUNNER_ENVIRONMENT_ERRORS), re.IGNORECASE)


def check_no_unexpected_errors(client, *, since: int = 0) -> None:
    """nvda.log.assert_no_errors(), minus what a headless runner logs by itself."""
    environmental, unexpected = [], []
    for record in client.log.errors(since=since):
        target = environmental if _RUNNER_ENVIRONMENT.search(record.message) else unexpected
        target.append(record)

    if environmental:
        joined = "; ".join(str(r) for r in environmental)
        warnings.warn(
            f"ignored {len(environmental)} runner-environment error(s): {joined}",
            stacklevel=2,
        )
    if unexpected:
        listed = "\n".join(f"  {r}" for r in unexpected)
        allow_listed = "\n".join(f"  {r}" for r in environmental) or "  (none)"
        raise AssertionError(
            f"NVDA logged {len(unexpected)} unexpected error(s):\n{listed}"
            f"\n\nAlso logged, and allowlisted as runner-environment noise:\n{allow_listed}"
        )


@pytest.fixture
def assert_no_unexpected_errors():
    return check_no_unexpected_errors


def wait_until(
    predicate: Callable[[], Any],
    *,
    timeout: float,
    interval: float = 0.5,
    description: str,
) -> Any:
    """Poll `predicate` until it returns something truthy, or raise on timeout.

    nvda-addon-testkit's namespaces have no generic "wait for a UI control's
    state" primitive -- speech.wait_for/log.wait_for only see NVDA's own
    speech and log output, which a background thread silently filling a
    wx.Choice never produces. This is the fallback for exactly that case.
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {description}; last seen: {last!r}")


def voice_manager_state(nvda, expr: str) -> Any:
    """Evaluate `expr` inside NVDA against the current top-level window.

    `expr` sees `dialog` (wx.GetActiveWindow()) and `wx`. Read-only use only
    -- see the "Global Constraints" note on nvda.eval() in the plan this
    helper was written from. Requires allow-eval = true in pyproject.toml.
    """
    return nvda.eval(
        "(lambda wx, dialog: " + expr + ")(__import__('wx'), __import__('wx').GetActiveWindow())"
    )
```

- [ ] **Step 3: Verify locally**

```bash
cd /path/to/dengjen-nvda
python -m pytest tests_e2e/ --collect-only -q
```

Expected: `no tests ran in ...s` (or similar), exit code 5 (pytest's "no tests collected" code) or 0 — either way, **no import errors or tracebacks**. This confirms `collect_ignore_glob` is skipping the (currently nonexistent) test files correctly and the conftest itself imports cleanly on Linux.

- [ ] **Step 4: Commit**

```bash
git add tests_e2e/__init__.py tests_e2e/conftest.py
git commit -m "test: scaffold the tests_e2e/ conftest for real-NVDA testing"
```

---

### Task 3: Install lifecycle + the real startup modal, and CI wiring

**Files:**
- Create: `tests_e2e/test_voice_manager.py`
- Modify: `.github/workflows/build_addon.yml`

**Interfaces:**
- Consumes: `check_no_unexpected_errors`/`assert_no_unexpected_errors` fixture, `wait_until`, `voice_manager_state` from `tests_e2e/conftest.py` (Task 2); `nvda`, `addon_bundle`, `addon_under_test` fixtures and `AddonState` from the `nvda_testkit` plugin (Task 1's dependency).
- Produces: nothing further tasks in this file don't already know how to extend (this task establishes the file; Tasks 4-6 append to it).

This task is the first one whose test content can only be verified in CI, so it also wires the CI job — there is no point creating the job before there is anything for it to run, and no point writing more tests before confirming the harness itself works end to end in CI.

- [ ] **Step 1: Write `tests_e2e/test_voice_manager.py`, part 1 (install lifecycle + no-voice modal)**

```python
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
```

- [ ] **Step 2: Add the `e2e` job to `.github/workflows/build_addon.yml`**

Insert after the `build` job (so it can reuse the `packaged_addon` artifact the same way `upload_release` already does) and before `upload_release`:

```yaml
  e2e:
    runs-on: windows-2025
    permissions:
      contents: read
    needs: ["build"]
    # Real network calls to Hugging Face for voice downloads (added in a
    # later task) make this slower and flakier than the deterministic
    # suites. Kept out of the `test` gate deliberately -- see the plan this
    # job was written from.
    continue-on-error: true
    steps:
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: "3.13"

      - name: download built addon
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
        with:
          name: packaged_addon

      - name: Install e2e test dependencies
        run: pip install --only-binary :all: -r requirements-test-e2e.txt

      - name: Cache NVDA launcher
        uses: actions/cache@v4
        with:
          path: ~/.cache/nvda-testkit
          key: nvda-launcher-stable-${{ github.run_id }}
          restore-keys: nvda-launcher-stable-

      - run: nvda-testkit doctor
      - run: pytest tests_e2e/ -v

      - if: failure()
        uses: actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4 # v5.0.0
        with:
          name: e2e-artifacts
          path: testOutput/
          if-no-files-found: warn
```

- [ ] **Step 3: Verify the workflow YAML is valid locally**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/build_addon.yml'))" && echo "YAML OK"
```

Expected: `YAML OK`, no exception.

- [ ] **Step 4: Verify the test file collects cleanly on Linux**

```bash
python -m pytest tests_e2e/ --collect-only -q
```

Expected: still 0 items collected (Linux `collect_ignore_glob` still applies), no import errors. This does **not** prove the tests pass — only that they don't have a syntax/import error that would fail before ever reaching Windows CI.

- [ ] **Step 5: Commit, push, and verify in CI**

```bash
git add tests_e2e/test_voice_manager.py .github/workflows/build_addon.yml
git commit -m "test: add e2e install-lifecycle and no-voice-modal tests, wire e2e CI job"
git push
```

Open the pushed branch's `e2e` check in GitHub Actions and read the `pytest tests_e2e/ -v` step output.

Expected: both tests pass. If `test_the_no_voice_modal_appears_and_no_declines_it` times out on `speech.wait_for`, the likely culprits, in order of likelihood: the modal's 3-second `wx.CallLater` hasn't fired yet (bump the 15s timeout), or NVDA didn't actually announce it (check the full speech transcript via `nvda.speech.all()` — add a debug print temporarily if needed). This is exactly the kind of tuning the plan's Global Constraints section calls out as expected on the first real run.

---

### Task 4: Voice download test

**Files:**
- Modify: `tests_e2e/test_voice_manager.py`

**Interfaces:**
- Consumes: same fixtures/helpers as Task 3, plus the file's module-level constants (`NO_VOICE_MODAL_TEXT`).
- Produces: `INSTALLED_VOICE_KEY` is *not* a module constant — the downloaded voice's key is read back at runtime in this test and reused by Task 5's test via a session-scoped fixture, `downloaded_voice_key`, added in this task.

This test drives the real voice manager dialog: reopen it via the no-voice modal, switch to the Download tab, pick a language, pick the first voice in that language that has an RT (fast) variant available, download it, and confirm it's listed as installed. Real keyboard input drives every action (tab switch, choice selection, list navigation, button activation); `voice_manager_state` (an `nvda.eval()` read, never a click) is used only to wait for background-thread state and to pick a safe voice index — `download_button_state` in `voice_manager_logic.py:78-83` disables the fast-variant button for a voice that has none, so blindly picking index 0 could silently no-op the button press.

- [ ] **Step 1: Append the download test and its supporting fixture**

```python
@pytest.fixture(scope="session")
def downloaded_voice_key(nvda, addon_under_test):
    """Downloads one real voice via the real dialog, once per session.
    Tests 4 (this) and 5 (real speech) both need a voice actually on disk;
    this fixture is where that happens so speech-focused tests don't also
    have to drive the download UI."""
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
```

- [ ] **Step 2: Verify locally (collection only)**

```bash
python -m pytest tests_e2e/ --collect-only -q
```

Expected: still 0 items on Linux, no import/syntax errors.

- [ ] **Step 3: Commit, push, and verify in CI**

```bash
git add tests_e2e/test_voice_manager.py
git commit -m "test: add e2e voice-download test"
git push
```

Read the `e2e` job's output. Expected: `test_downloading_the_fast_variant_voice_installs_it` passes. Likely tuning points if it doesn't (per the plan's Global Constraints):
- If `control+tab` doesn't switch notebook pages: confirm focus was actually inside the dialog first (the modal's Yes button press may need a brief settle — add a short `nvda.wait_until_idle()` call after `nvda.keys.press("y")` before pressing `control+tab`).
- If the `tab` chain lands somewhere other than the fast-variant button: cross-check against the confirmed real tab order from `tests_gui/test_voice_manager_dialog.py`'s `test_the_download_pages_controls_all_precede_the_close_button` (`language_choice → voices_list → preview_btn → download_std_btn → download_rt_btn → refresh_button → close`) — that test asserts this order against real wxPython, so a mismatch here points at a state difference (e.g., `buttons_panel` not yet enabled when the tabs are pressed), not a wrong assumption about ordering.

---

### Task 5: Real speech test

**Files:**
- Modify: `tests_e2e/test_voice_manager.py`

**Interfaces:**
- Consumes: `downloaded_voice_key` fixture (Task 4).

Switches NVDA's active synthesizer to Dengjen via `nvda.config` (the same mechanism NVDA's own startup uses to pick a synth — reading `config.conf["speech"]["synth"]` — not a mock of it) and confirms real speech round-trips. Note what this does and doesn't prove: `nvda.speech` captures the text *requested* of NVDA's speech subsystem, not audio — so this proves the Dengjen driver initializes with a real downloaded voice and processes a speak request without erroring (which `tests_contract/` and `tests_gui/` cannot prove together, since neither drives a real downloaded voice through a real NVDA process), not that audio was actually produced.

- [ ] **Step 1: Append the speech test**

```python
def test_the_downloaded_voice_produces_real_speech(nvda, downloaded_voice_key, assert_no_unexpected_errors):
    nvda.config.set(["speech", "synth"], ADDON_NAME)
    nvda.config.set(["speech", ADDON_NAME, "voice"], downloaded_voice_key)
    nvda.restart()  # NVDA reads config.conf["speech"]["synth"] on startup

    before = nvda.speech.index()
    phrase = "dengjen testkit smoke phrase"
    nvda.speech.speak(phrase)
    found = nvda.speech.wait_for(phrase, timeout=15, since=before)
    assert phrase in found.text.lower()
    assert_no_unexpected_errors(nvda)
```

- [ ] **Step 2: Verify locally (collection only)**

```bash
python -m pytest tests_e2e/ --collect-only -q
```

Expected: still 0 items on Linux, no import/syntax errors.

- [ ] **Step 3: Commit, push, and verify in CI**

```bash
git add tests_e2e/test_voice_manager.py
git commit -m "test: add e2e real-speech test against the downloaded voice"
git push
```

Read the `e2e` job's output. Expected: passes, and `assert_no_unexpected_errors` in particular confirms the driver didn't error while loading the just-downloaded voice or synthesizing with it — that's the highest-value assertion in this test, more so than the text echo.

---

### Task 6: Removal test and suite finalization

**Files:**
- Modify: `tests_e2e/test_voice_manager.py`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: `downloaded_voice_key` fixture (Task 4), `ADDON_NAME` constant (Task 3).

Must run last: it tears down what `addon_under_test` set up, and that session-scoped fixture will not reinstall itself for a test later in the same session. Same convention as nvda-addon-testkit's own `test_removal_is_also_two_phase`.

- [ ] **Step 1: Append the removal test**

```python
def test_removal_is_also_two_phase(nvda):
    """Must stay last in this file: uninstalls what addon_under_test set up."""
    nvda.addons.remove(ADDON_NAME)
    assert nvda.addons.state(ADDON_NAME) is AddonState.PENDING_REMOVE
    nvda.restart()
    assert nvda.addons.state(ADDON_NAME) is AddonState.NOT_INSTALLED
```

- [ ] **Step 2: Document the new suite in `CONTRIBUTING.md`**

Read `CONTRIBUTING.md` first to match its existing structure for documenting `tests_gui/`/`tests_contract/` (search for how those two are introduced), then add an equivalent short section for `tests_e2e/`: what it is, that it's Windows-only and CI-only (not runnable locally on this project's dev machines), and the command (`pytest tests_e2e/ -v`) plus the one-time `nvda-testkit doctor` sanity check.

- [ ] **Step 3: Verify locally (collection only)**

```bash
python -m pytest tests_e2e/ --collect-only -q
```

Expected: still 0 items on Linux, no import/syntax errors.

- [ ] **Step 4: Commit, push, and verify in CI**

```bash
git add tests_e2e/test_voice_manager.py CONTRIBUTING.md
git commit -m "test: add e2e removal test, document tests_e2e/ in CONTRIBUTING"
git push
```

Read the `e2e` job's output. Expected: **all five tests in `tests_e2e/test_voice_manager.py` pass** (`downloaded_voice_key` is a fixture, not a test, so it doesn't count as a sixth), in this order:

1. `test_install_is_two_phase_and_completes_on_restart`
2. `test_the_no_voice_modal_appears_and_no_declines_it`
3. `test_downloading_the_fast_variant_voice_installs_it`
4. `test_the_downloaded_voice_produces_real_speech`
5. `test_removal_is_also_two_phase`

This is the full pipeline from the design: real install, real modal, real download, real speech, real teardown.
