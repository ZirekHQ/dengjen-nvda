"""Regression coverage for wait_until's RpcError tolerance (issue #174).

Pure-Python: wait_until only ever calls the predicate it's given, so these
drive it with fakes instead of a real NVDA -- unlike test_voice_manager.py,
nothing here needs the nvda fixture.
"""

from __future__ import annotations

import sys

import pytest

if sys.platform == "win32":
    from nvda_testkit.errors import AuthError, RpcError

from .conftest import press_until, wait_until


def test_retries_past_a_transient_rpc_error(monkeypatch):
    attempts = iter(
        [RpcError("NVDA between windows"), RpcError("still between"), "ready"]
    )

    def predicate():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    assert wait_until(predicate, timeout=5, description="the flaky state") == "ready"


def test_times_out_with_the_last_rpc_error_attached(monkeypatch):
    exc = RpcError("NVDA between windows")

    def predicate():
        raise exc

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    clock = iter([0, 0, 10])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))

    with pytest.raises(AssertionError, match="the flaky state") as excinfo:
        wait_until(predicate, timeout=5, description="the flaky state")

    assert excinfo.value.__cause__ is exc


def test_a_later_falsy_result_does_not_drop_an_earlier_rpc_error(monkeypatch):
    exc = RpcError("NVDA between windows")
    attempts = iter([exc, False])

    def predicate():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    clock = iter([0, 0, 0, 10])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))

    with pytest.raises(AssertionError) as excinfo:
        wait_until(predicate, timeout=5, description="the flaky state")

    assert excinfo.value.__cause__ is exc


class _FakeKeys:
    def __init__(self, on_press):
        self.presses = 0
        self._on_press = on_press

    def press(self, _gesture):
        self.presses += 1
        self._on_press(self.presses)


class _FakeNvda:
    def __init__(self, on_press):
        self.keys = _FakeKeys(on_press)


def test_press_until_does_not_repeat_a_press_that_landed_late(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    clock = iter([0, 0, 10, 10])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    landed = {"tab": 0}
    nvda = _FakeNvda(lambda _n: None)

    def predicate():
        if nvda.keys.presses == 1 and landed["tab"] == 0:
            landed["tab"] = 1
            return False
        return landed["tab"] == 1

    press_until(nvda, "control+tab", predicate, attempts=3, timeout=5)

    assert nvda.keys.presses == 1


def test_press_until_does_not_press_when_the_goal_already_holds():
    nvda = _FakeNvda(lambda _n: None)

    press_until(nvda, "control+tab", lambda: True, attempts=3, timeout=5)

    assert nvda.keys.presses == 0


def test_press_until_rereads_the_state_after_a_transient_rpc_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    states = iter([RpcError("between windows"), True])
    nvda = _FakeNvda(lambda _n: None)

    def predicate():
        state = next(states)
        if isinstance(state, Exception):
            raise state
        return state

    press_until(nvda, "control+tab", predicate, attempts=3, timeout=5)

    assert nvda.keys.presses == 0


def test_press_until_does_not_press_blind_when_the_state_stays_unreadable(
    monkeypatch,
):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    nvda = _FakeNvda(lambda _n: None)

    def predicate():
        raise RpcError("between windows")

    with pytest.raises(AssertionError, match="could not read the state"):
        press_until(nvda, "control+tab", predicate, attempts=3, timeout=5)

    assert nvda.keys.presses == 0


def test_press_until_retries_a_press_that_was_swallowed(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    clock = iter([0, 10, 10, 20, 20])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    nvda = _FakeNvda(lambda _n: None)

    press_until(nvda, "tab", lambda: nvda.keys.presses >= 2, attempts=3, timeout=5)

    assert nvda.keys.presses == 2


def test_an_auth_error_is_not_retried(monkeypatch):
    exc = AuthError("stale token")
    calls = 0

    def predicate():
        nonlocal calls
        calls += 1
        raise exc

    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(AuthError):
        wait_until(predicate, timeout=5, description="a fresh NVDA connection")

    assert calls == 1
