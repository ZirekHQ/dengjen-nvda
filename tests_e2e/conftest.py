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
from collections.abc import Callable
from typing import Any

import pytest

collect_ignore_glob = [] if sys.platform == "win32" else ["test_*.py"]


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
        target = (
            environmental if _RUNNER_ENVIRONMENT.search(record.message) else unexpected
        )
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
    -- a synchronization/assertion oracle, never a way to drive controls;
    driving goes through nvda.keys, because proving real keyboard
    reachability against a real NVDA is the point of this suite. Requires
    allow-eval = true in pyproject.toml.
    """
    return nvda.eval(
        "(lambda wx, dialog: "
        + expr
        + ")(__import__('wx'), __import__('wx').GetActiveWindow())"
    )


def press_until(
    nvda,
    gesture: str,
    predicate: Callable[[], Any],
    *,
    attempts: int = 5,
    timeout: float = 2.0,
    description: str = "",
) -> None:
    """Retry a keystroke whose effect can be silently swallowed by a UI-focus
    race, polling `predicate` (a read-only check, e.g. via voice_manager_state)
    after each press. Re-raises the last timeout if every attempt fails.
    """
    for attempt in range(attempts):
        nvda.keys.press(gesture)
        try:
            wait_until(
                predicate,
                timeout=timeout,
                description=description or f"{gesture!r} to land",
            )
            return
        except AssertionError:
            if attempt == attempts - 1:
                raise
