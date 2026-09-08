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

from .conftest import wait_until


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
