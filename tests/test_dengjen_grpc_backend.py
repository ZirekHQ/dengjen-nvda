"""
Tests for DengjenGrpcBackend's TTSBackend surface: that it correctly
translates the underlying module-level gRPC calls' failures into the
TTSBackend port's typed errors. The gRPC calls themselves (against a real
dengjen-tts-grpc.exe) are covered by tests_contract/, not here.
"""

import os
import types
from concurrent.futures import Future

import pytest
from dengjen_neural_voices.adapters import dengjen_grpc
from dengjen_neural_voices.ports.tts_backend import (
    BackendUnavailableError,
    SynthesisError,
    VoiceLoadError,
)

backend = dengjen_grpc.DengjenGrpcBackend()


def _failed_future(exc):
    f = Future()
    f.set_exception(exc)
    return f


def _resolved_future(value):
    f = Future()
    f.set_result(value)
    return f


def test_initialize_wraps_a_failure_as_backend_unavailable(monkeypatch):
    monkeypatch.setattr(
        dengjen_grpc, "initialize", lambda: _failed_future(RuntimeError("no port"))
    )
    with pytest.raises(BackendUnavailableError):
        backend.initialize()


def test_check_version_wraps_a_failure_as_backend_unavailable(monkeypatch):

    monkeypatch.setattr(
        dengjen_grpc, "check_grpc_server", lambda: _failed_future(TimeoutError())
    )
    monkeypatch.setattr(
        dengjen_grpc, "initialize", lambda: _failed_future(RuntimeError("no port"))
    )
    with pytest.raises(BackendUnavailableError):
        backend.check_version()


def test_check_version_retries_once_after_a_failed_handshake_and_succeeds(monkeypatch):
    """The retry this backend needs when the first handshake fails for
    any transient reason (#143): a fresh initialize() is attempted, and
    the second handshake succeeds."""
    attempts = []

    def _check_grpc_server():
        attempts.append(None)
        if len(attempts) == 1:
            return _failed_future(TimeoutError())
        return _resolved_future("1.2.3")

    monkeypatch.setattr(dengjen_grpc, "check_grpc_server", _check_grpc_server)
    monkeypatch.setattr(dengjen_grpc, "initialize", lambda: _resolved_future(None))

    assert backend.check_version() == "1.2.3"
    assert len(attempts) == 2


def test_check_version_gives_up_as_backend_unavailable_after_one_failed_retry(
    monkeypatch,
):
    """The retry is bounded: a second consecutive failure still surfaces as
    BackendUnavailableError rather than looping indefinitely."""
    attempts = []

    def _check_grpc_server():
        attempts.append(None)
        return _failed_future(TimeoutError())

    monkeypatch.setattr(dengjen_grpc, "check_grpc_server", _check_grpc_server)
    monkeypatch.setattr(dengjen_grpc, "initialize", lambda: _resolved_future(None))

    with pytest.raises(BackendUnavailableError):
        backend.check_version()

    assert len(attempts) == 2


def test_load_voice_wraps_a_failure_as_voice_load_error(monkeypatch):
    monkeypatch.setattr(
        dengjen_grpc,
        "load_voice",
        lambda path: _failed_future(RuntimeError("bad proto")),
    )
    with pytest.raises(VoiceLoadError):
        backend.load_voice("/tmp/v/config.json")


def test_load_voice_maps_the_response_fields(monkeypatch):
    class _FakeInfo:
        voice_key = "v1"
        supports_streaming_output = True

        class audio:
            sample_rate = 22050

        speakers = {"0": "Alice"}

        class synthesis_options:
            speaker = "Alice"
            length_scale = 1.0
            noise_scale = 0.5
            noise_w = 0.8

    ready = Future()
    ready.set_result(_FakeInfo())
    monkeypatch.setattr(dengjen_grpc, "load_voice", lambda path: ready)

    loaded = backend.load_voice("/tmp/v/config.json")

    assert loaded.backend_voice_id == "v1"
    assert loaded.sample_rate == 22050
    assert loaded.speakers == {"0": "Alice"}
    assert loaded.defaults.noise_scale == 0.5


def test_set_synth_options_wraps_a_failure_as_voice_load_error(monkeypatch):
    monkeypatch.setattr(
        dengjen_grpc,
        "set_synth_options",
        lambda voice_id, **kw: _failed_future(RuntimeError("boom")),
    )
    with pytest.raises(VoiceLoadError):
        backend.set_synth_options("v1", noise_scale=0.5)


def test_synthesize_wraps_a_failure_as_synthesis_error():
    import asyncio

    async def _boom(**kwargs):
        raise RuntimeError("stream broke")
        yield b""

    async def _run():
        with pytest.raises(SynthesisError):
            async for _ in backend.synthesize(
                "v1", "hi", None, None, None, None, False
            ):
                pass

    import dengjen_neural_voices.adapters.dengjen_grpc as mod

    orig = mod.speak
    mod.speak = _boom
    try:
        asyncio.run(_run())
    finally:
        mod.speak = orig


def test_synthesize_yields_audio_bytes_not_the_raw_message():
    """Regression test: synthesize() briefly re-yielded the raw protobuf
    message instead of unwrapping .audio_bytes (caught and fixed during this
    branch's own work). speak() yields message-shaped objects, not bytes, so
    a fixture asserting bytes-in/bytes-out here would pass even if
    synthesize() forgot to extract .audio_bytes."""
    import asyncio
    import types

    async def _fake_speak(**kwargs):
        yield types.SimpleNamespace(audio_bytes=b"abc")
        yield types.SimpleNamespace(audio_bytes=b"def")

    async def _run():
        return [
            chunk
            async for chunk in backend.synthesize(
                "v1", "hi", None, None, None, None, False
            )
        ]

    import dengjen_neural_voices.adapters.dengjen_grpc as mod

    orig = mod.speak
    mod.speak = _fake_speak
    try:
        chunks = asyncio.run(_run())
    finally:
        mod.speak = orig

    assert chunks == [b"abc", b"def"]


class TestClearStaleServerState:
    """_clear_stale_server_state() is the recovery path for a server that
    Popen'd successfully but never became reachable (e.g. crashed after
    binding, or hung before answering RPCs) -- without it, every
    later start_grpc_server()/initialize() call would keep reusing the same
    dead process, port and channel forever, since their cache checks only
    look at presence, not health.

    It's an async function (it awaits the channel's own close() rather than
    close_channel()'s thread-hop, which would deadlock when called from the
    aio loop it's already running on -- see its docstring), so every test
    here drives it with asyncio.run(), same as the synthesize() tests
    above."""

    def test_kills_the_cached_process_and_clears_module_globals(self, monkeypatch):
        import asyncio
        import types

        killed = types.SimpleNamespace(value=False)
        fake_process = types.SimpleNamespace(
            kill=lambda: setattr(killed, "value", True)
        )
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", fake_process)
        monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVER_PORT", 12345)

        asyncio.run(dengjen_grpc._clear_stale_server_state())

        assert killed.value
        assert dengjen_grpc.GRPC_SERVER_PROCESS is None
        assert dengjen_grpc.DENGJEN_GRPC_SERVER_PORT is None

    def test_closes_and_clears_the_channel_and_service(self, monkeypatch):
        import asyncio
        import types

        closed = types.SimpleNamespace(value=False)

        class _FakeChannel:
            async def close(self):
                closed.value = True

        monkeypatch.setattr(dengjen_grpc, "CHANNEL", _FakeChannel())
        monkeypatch.setattr(dengjen_grpc, "CHANNEL_PORT", 50051)
        monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVICE", object())

        asyncio.run(dengjen_grpc._clear_stale_server_state())

        assert closed.value
        assert dengjen_grpc.CHANNEL is None
        assert dengjen_grpc.CHANNEL_PORT is None
        assert dengjen_grpc.DENGJEN_GRPC_SERVICE is None

    def test_a_channel_that_fails_to_close_does_not_stop_the_rest_of_the_cleanup(
        self, monkeypatch
    ):
        import asyncio
        import types

        class _FakeChannel:
            async def close(self):
                raise Exception("channel already broken")

        killed = types.SimpleNamespace(value=False)
        fake_process = types.SimpleNamespace(
            kill=lambda: setattr(killed, "value", True)
        )
        monkeypatch.setattr(dengjen_grpc, "CHANNEL", _FakeChannel())
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", fake_process)

        asyncio.run(dengjen_grpc._clear_stale_server_state())

        assert dengjen_grpc.CHANNEL is None
        assert killed.value

    def test_clears_the_globalVars_cache(self):

        import asyncio

        import globalVars

        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = object()

        asyncio.run(dengjen_grpc._clear_stale_server_state())

        assert not hasattr(globalVars, "DENGJEN_GRPC_SERVER_PORT")
        assert not hasattr(globalVars, "GRPC_SERVER_PROCESS")

    def test_closes_the_server_log_handle(self, monkeypatch):
        import asyncio
        import types

        closed = types.SimpleNamespace(value=False)
        fake_handle = types.SimpleNamespace(
            close=lambda: setattr(closed, "value", True)
        )
        monkeypatch.setattr(dengjen_grpc, "SERVER_LOG_HANDLE", fake_handle)

        asyncio.run(dengjen_grpc._clear_stale_server_state())

        assert closed.value
        assert dengjen_grpc.SERVER_LOG_HANDLE is None

    def test_is_a_noop_when_nothing_is_cached(self, monkeypatch):
        import asyncio

        import globalVars

        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", None)
        monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVER_PORT", None)
        monkeypatch.setattr(dengjen_grpc, "SERVER_LOG_HANDLE", None)
        monkeypatch.setattr(dengjen_grpc, "CHANNEL", None)
        monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVICE", None)
        monkeypatch.delattr(globalVars, "DENGJEN_GRPC_SERVER_PORT", raising=False)
        monkeypatch.delattr(globalVars, "GRPC_SERVER_PROCESS", raising=False)

        asyncio.run(dengjen_grpc._clear_stale_server_state())

    def test_a_process_that_refuses_to_die_does_not_stop_the_cleanup(self, monkeypatch):
        import asyncio
        import types

        fake_process = types.SimpleNamespace(
            kill=lambda: (_ for _ in ()).throw(Exception("access denied"))
        )
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", fake_process)

        asyncio.run(dengjen_grpc._clear_stale_server_state())

        assert dengjen_grpc.GRPC_SERVER_PROCESS is None


def test_check_grpc_server_clears_stale_state_when_the_handshake_fails():
    """The wiring half of TestClearStaleServerState: exercises
    check_grpc_server()'s real try/except body -- not a reimplementation of
    it -- and confirms a failed handshake actually triggers the cleanup
    rather than just leaving it available unused.

    Calls the coroutine function directly (asyncio.run), same as the
    synthesize() tests above: @aio.asyncio_coroutine_to_concurrent_future is
    stubbed to the identity function in tests (nvda_stubs.py), so
    check_grpc_server is the plain coroutine function here, not a
    Future-returning wrapper -- unlike in production, where the real aio
    engine backs it.
    """
    import asyncio
    import types

    import dengjen_neural_voices.adapters.dengjen_grpc as mod

    killed = types.SimpleNamespace(value=False)
    fake_process = types.SimpleNamespace(kill=lambda: setattr(killed, "value", True))

    orig_get_version = mod.get_dengjen_version
    orig_process = mod.GRPC_SERVER_PROCESS

    async def _boom():
        raise RuntimeError("connection refused")

    mod.get_dengjen_version = _boom
    mod.GRPC_SERVER_PROCESS = fake_process
    try:
        coro = mod.check_grpc_server()
        with pytest.raises(RuntimeError):
            asyncio.run(coro)
    finally:
        mod.get_dengjen_version = orig_get_version
        mod.GRPC_SERVER_PROCESS = orig_process

    assert killed.value
    assert mod.GRPC_SERVER_PROCESS is None


class TestWaitForListeningPort:
    def test_returns_the_port_once_the_log_contains_the_handshake_line(self, tmp_path):
        import types

        log_path = tmp_path / "server.log"
        log_path.write_bytes(b"DENGJEN_GRPC_LISTENING port=49314\n")
        process = types.SimpleNamespace(poll=lambda: None)

        port = dengjen_grpc._wait_for_listening_port(process, str(log_path), timeout=1)

        assert port == 49314

    def test_ignores_unrelated_log_lines_before_the_handshake_appears(self, tmp_path):
        import types

        log_path = tmp_path / "server.log"
        log_path.write_bytes(
            b"[INFO] starting up\n"
            b"[INFO] loading onnxruntime\n"
            b"DENGJEN_GRPC_LISTENING port=51000\n"
        )
        process = types.SimpleNamespace(poll=lambda: None)

        port = dengjen_grpc._wait_for_listening_port(process, str(log_path), timeout=1)

        assert port == 51000

    def test_does_not_match_a_partially_written_line_without_a_trailing_newline(
        self, tmp_path
    ):
        import types

        log_path = tmp_path / "server.log"
        log_path.write_bytes(b"DENGJEN_GRPC_LISTENING port=493")
        process = types.SimpleNamespace(poll=lambda: None)

        with pytest.raises(TimeoutError):
            dengjen_grpc._wait_for_listening_port(
                process, str(log_path), timeout=0.1, poll_interval=0.02
            )

    def test_raises_timeout_error_when_the_line_never_appears(self, tmp_path):
        import types

        log_path = tmp_path / "server.log"
        log_path.write_bytes(b"")
        process = types.SimpleNamespace(poll=lambda: None)

        with pytest.raises(TimeoutError):
            dengjen_grpc._wait_for_listening_port(
                process, str(log_path), timeout=0.1, poll_interval=0.02
            )

    def test_raises_runtime_error_when_the_process_exits_before_reporting(
        self, tmp_path
    ):
        import types

        log_path = tmp_path / "server.log"
        log_path.write_bytes(b"")
        process = types.SimpleNamespace(poll=lambda: 1)

        with pytest.raises(RuntimeError, match="exit code: 1"):
            dengjen_grpc._wait_for_listening_port(process, str(log_path), timeout=1)

    def test_raises_runtime_error_immediately_without_waiting_out_the_timeout(
        self, tmp_path
    ):
        """The process already died -- must not wait out the full timeout budget."""
        import time
        import types

        log_path = tmp_path / "server.log"
        log_path.write_bytes(b"")
        process = types.SimpleNamespace(poll=lambda: 1)

        start = time.monotonic()
        with pytest.raises(RuntimeError):
            dengjen_grpc._wait_for_listening_port(process, str(log_path), timeout=5)
        assert time.monotonic() - start < 1


class _FakeStaleProc:
    """A psutil.Process double for the abandoned-helper reaper below."""

    def __init__(self, name, exe, pid=1, parent_pid=None, terminate_error=None):
        self._name = name
        self._exe = exe
        self.pid = pid
        self._parent_pid = parent_pid
        self._terminate_error = terminate_error
        self.terminated = False

    def name(self):
        return self._name

    def exe(self):
        return self._exe

    def parent(self):
        if self._parent_pid is None:
            return None
        return types.SimpleNamespace(pid=self._parent_pid)

    def terminate(self):
        if self._terminate_error is not None:
            raise self._terminate_error
        self.terminated = True


class _FakePsutilModule:
    """A psutil module double: process_iter()/wait_procs() are all the
    reaper needs, so this stands in for `import psutil` via sys.modules."""

    def __init__(self, processes):
        self._processes = processes
        self.wait_calls = []

    def process_iter(self, attrs=None):
        return iter(self._processes)

    def wait_procs(self, processes, timeout=None):
        self.wait_calls.append((list(processes), timeout))
        gone = [p for p in processes if p.terminated]
        alive = [p for p in processes if not p.terminated]
        return gone, alive


class TestMatchesGrpcExeAndOwnership:
    def test_matches_same_name_and_exe_path(self, monkeypatch):
        monkeypatch.setattr(os.path, "samefile", lambda a, b: str(a) == str(b))
        proc = _FakeStaleProc("dengjen-tts-grpc.exe", "/x/dengjen-tts-grpc.exe")

        assert dengjen_grpc._matches_grpc_exe(proc, "/x/dengjen-tts-grpc.exe")

    def test_matches_the_process_name_case_insensitively(self, monkeypatch):
        monkeypatch.setattr(os.path, "samefile", lambda a, b: True)
        proc = _FakeStaleProc("DENGJEN-TTS-GRPC.EXE", "/x")

        assert dengjen_grpc._matches_grpc_exe(proc, "/x")

    def test_ignores_an_unrelated_process_name(self):
        proc = _FakeStaleProc("firefox", "/usr/bin/firefox")

        assert not dengjen_grpc._matches_grpc_exe(proc, "/x/dengjen-tts-grpc.exe")

    def test_does_not_match_a_same_named_exe_from_another_location(self, monkeypatch):
        monkeypatch.setattr(os.path, "samefile", lambda a, b: str(a) == str(b))
        proc = _FakeStaleProc(
            "dengjen-tts-grpc.exe", "/tmp/elsewhere/dengjen-tts-grpc.exe"
        )

        assert not dengjen_grpc._matches_grpc_exe(proc, "/x/dengjen-tts-grpc.exe")

    def test_a_process_whose_name_cannot_be_read_is_not_a_match(self):
        class _Unreadable:
            def name(self):
                raise Exception("gone")

        assert not dengjen_grpc._matches_grpc_exe(_Unreadable(), "/x")

    def test_a_stale_exe_path_is_not_a_match(self, monkeypatch):
        monkeypatch.setattr(
            os.path, "samefile", lambda a, b: (_ for _ in ()).throw(FileNotFoundError())
        )
        proc = _FakeStaleProc("dengjen-tts-grpc.exe", "/x/dengjen-tts-grpc.exe")

        assert not dengjen_grpc._matches_grpc_exe(proc, "/x/dengjen-tts-grpc.exe")

    def test_owned_when_the_parent_is_this_process(self):
        proc = _FakeStaleProc("x", "/x", parent_pid=os.getpid())

        assert dengjen_grpc._owned_by_this_process(proc)

    def test_not_owned_when_the_parent_is_a_different_process(self):
        proc = _FakeStaleProc("x", "/x", parent_pid=os.getpid() + 1)

        assert not dengjen_grpc._owned_by_this_process(proc)

    def test_not_owned_when_there_is_no_parent(self):
        proc = _FakeStaleProc("x", "/x", parent_pid=None)

        assert not dengjen_grpc._owned_by_this_process(proc)

    def test_not_owned_when_the_parent_lookup_fails(self):
        class _NoParent:
            def parent(self):
                raise Exception("gone")

        assert not dengjen_grpc._owned_by_this_process(_NoParent())


class TestFindStaleGrpcHelpers:
    def test_returns_only_same_exe_processes_owned_by_this_process(self, monkeypatch):
        monkeypatch.setattr(os.path, "samefile", lambda a, b: str(a) == str(b))
        exe = "/x/dengjen-tts-grpc.exe"
        ours = _FakeStaleProc(
            "dengjen-tts-grpc.exe", exe, pid=1, parent_pid=os.getpid()
        )
        another_nvda_instance = _FakeStaleProc(
            "dengjen-tts-grpc.exe", exe, pid=2, parent_pid=os.getpid() + 1
        )
        unrelated = _FakeStaleProc("bash", "/bin/bash", pid=3, parent_pid=os.getpid())
        psutil = _FakePsutilModule([ours, another_nvda_instance, unrelated])

        assert dengjen_grpc._find_stale_grpc_helpers(psutil, exe) == [ours]


class TestTerminateStaleGrpcHelpers:
    def test_is_a_noop_for_an_empty_list(self):
        psutil = _FakePsutilModule([])

        dengjen_grpc._terminate_stale_grpc_helpers(psutil, [])

        assert psutil.wait_calls == []

    def test_terminates_and_waits_with_the_bounded_timeout(self):
        proc = _FakeStaleProc("dengjen-tts-grpc.exe", "/x", pid=1)
        psutil = _FakePsutilModule([proc])

        dengjen_grpc._terminate_stale_grpc_helpers(psutil, [proc])

        assert proc.terminated
        assert psutil.wait_calls == [([proc], dengjen_grpc.PROCESS_EXIT_TIMEOUT)]

    def test_one_process_failing_to_terminate_does_not_stop_the_others(self):
        stubborn = _FakeStaleProc(
            "x", "/x", pid=1, terminate_error=Exception("access denied")
        )
        ours = _FakeStaleProc("x", "/x", pid=2)
        psutil = _FakePsutilModule([stubborn, ours])

        dengjen_grpc._terminate_stale_grpc_helpers(psutil, [stubborn, ours])

        assert not stubborn.terminated
        assert ours.terminated
        assert psutil.wait_calls == [
            ([stubborn, ours], dengjen_grpc.PROCESS_EXIT_TIMEOUT)
        ]


class TestReapStaleGrpcServers:
    """_reap_stale_grpc_servers() is the entry point start_grpc_server() runs
    off the aio loop thread. `import psutil` inside it resolves through
    sys.modules first, so injecting a fake there (or `None`, which CPython
    treats as an explicitly-disabled module and raises ImportError) drives
    it without needing the real, Windows-only vendored psutil build."""

    def test_logs_and_returns_when_psutil_is_unavailable(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "psutil", None)

        dengjen_grpc._reap_stale_grpc_servers("/x/dengjen-tts-grpc.exe")

    def test_finds_and_terminates_a_stale_same_pid_helper(self, monkeypatch):
        import sys

        monkeypatch.setattr(os.path, "samefile", lambda a, b: str(a) == str(b))
        exe = "/x/dengjen-tts-grpc.exe"
        proc = _FakeStaleProc(
            "dengjen-tts-grpc.exe", exe, pid=1, parent_pid=os.getpid()
        )
        monkeypatch.setitem(sys.modules, "psutil", _FakePsutilModule([proc]))

        dengjen_grpc._reap_stale_grpc_servers(exe)

        assert proc.terminated

    def test_an_exception_during_the_scan_is_logged_and_swallowed(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "psutil", _FakePsutilModule([]))
        monkeypatch.setattr(
            dengjen_grpc,
            "_find_stale_grpc_helpers",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scan broke")),
        )

        dengjen_grpc._reap_stale_grpc_servers("/x/dengjen-tts-grpc.exe")


class TestClearSavedServerState:
    def test_removes_both_attrs_when_present(self):
        import globalVars

        globalVars.DENGJEN_GRPC_SERVER_PORT = 1
        globalVars.GRPC_SERVER_PROCESS = object()

        dengjen_grpc._clear_saved_server_state()

        assert not hasattr(globalVars, "DENGJEN_GRPC_SERVER_PORT")
        assert not hasattr(globalVars, "GRPC_SERVER_PROCESS")

    def test_is_a_noop_when_nothing_is_saved(self, monkeypatch):
        import globalVars

        monkeypatch.delattr(globalVars, "DENGJEN_GRPC_SERVER_PORT", raising=False)
        monkeypatch.delattr(globalVars, "GRPC_SERVER_PROCESS", raising=False)

        dengjen_grpc._clear_saved_server_state()


class TestSavedServerIsAlive:
    def test_true_when_saved_and_poll_reports_running(self):
        import globalVars

        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = types.SimpleNamespace(poll=lambda: None)

        assert dengjen_grpc._saved_server_is_alive()

    def test_false_when_poll_reports_exited(self):
        import globalVars

        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = types.SimpleNamespace(poll=lambda: 1)

        assert not dengjen_grpc._saved_server_is_alive()

    def test_false_when_nothing_is_saved(self, monkeypatch):
        import globalVars

        monkeypatch.delattr(globalVars, "DENGJEN_GRPC_SERVER_PORT", raising=False)
        monkeypatch.delattr(globalVars, "GRPC_SERVER_PROCESS", raising=False)

        assert not dengjen_grpc._saved_server_is_alive()

    def test_false_when_poll_raises(self):
        import globalVars

        def _broken_poll():
            raise OSError("no such process")

        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = types.SimpleNamespace(poll=_broken_poll)

        assert not dengjen_grpc._saved_server_is_alive()


class TestReapIfNeeded:
    """_reap_if_needed() is what initialize() runs off the aio loop thread,
    before start_grpc_server() decides whether to reuse or respawn."""

    def test_skips_reaping_when_the_saved_process_is_alive(self, monkeypatch):
        monkeypatch.setattr(dengjen_grpc, "_saved_server_is_alive", lambda: True)
        reap_calls = []
        monkeypatch.setattr(dengjen_grpc, "_reap_stale_grpc_servers", reap_calls.append)

        dengjen_grpc._reap_if_needed("/x/dengjen-tts-grpc.exe")

        assert reap_calls == []

    def test_clears_state_and_reaps_when_the_saved_process_is_not_alive(
        self, monkeypatch
    ):
        import globalVars

        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = object()
        monkeypatch.setattr(dengjen_grpc, "_saved_server_is_alive", lambda: False)
        reap_calls = []
        monkeypatch.setattr(dengjen_grpc, "_reap_stale_grpc_servers", reap_calls.append)

        dengjen_grpc._reap_if_needed("/x/dengjen-tts-grpc.exe")

        assert not hasattr(globalVars, "DENGJEN_GRPC_SERVER_PORT")
        assert not hasattr(globalVars, "GRPC_SERVER_PROCESS")
        assert reap_calls == ["/x/dengjen-tts-grpc.exe"]


class TestStartGrpcServerReusesOrClearsSavedState:
    """start_grpc_server() used to trust a cached globalVars port/process
    blindly. It now only reuses it once _saved_server_is_alive() confirms
    it, and clears stale state before attempting a fresh spawn."""

    def test_returns_true_and_reuses_the_saved_process_when_alive(self, monkeypatch):
        import globalVars

        fake_process = types.SimpleNamespace(poll=lambda: None)
        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = fake_process
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", None)
        monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVER_PORT", None)

        result = dengjen_grpc.start_grpc_server()

        assert result is True
        assert dengjen_grpc.DENGJEN_GRPC_SERVER_PORT == 12345
        assert dengjen_grpc.GRPC_SERVER_PROCESS is fake_process

    def test_clears_stale_state_before_attempting_a_fresh_spawn(self, monkeypatch):
        import globalVars

        dead_process = types.SimpleNamespace(poll=lambda: 1)
        globalVars.DENGJEN_GRPC_SERVER_PORT = 12345
        globalVars.GRPC_SERVER_PROCESS = dead_process
        monkeypatch.setattr(dengjen_grpc, "_vcruntime_missing", lambda: True)
        monkeypatch.setattr(dengjen_grpc, "_show_vcruntime_warning", lambda: None)

        result = dengjen_grpc.start_grpc_server()

        assert result is False
        assert not hasattr(globalVars, "DENGJEN_GRPC_SERVER_PORT")
        assert not hasattr(globalVars, "GRPC_SERVER_PROCESS")


class TestInitializeReapsBeforeStarting:
    """initialize() runs _reap_if_needed() off the aio loop thread via
    aio.run_in_executor(), ahead of start_grpc_server() -- the reap's
    system-wide psutil scan must never block queued gRPC calls on that
    thread the way this module's blocking startup I/O already does, which
    is why it (unlike start_grpc_server() itself) goes through the
    executor instead of running inline."""

    def test_reaps_via_the_executor_before_starting_the_server(self, monkeypatch):
        import asyncio

        calls = []

        async def _fake_run_in_executor(func, *args, **kwargs):
            calls.append(("reap", func, args))
            return func(*args, **kwargs)

        monkeypatch.setattr(dengjen_grpc.aio, "run_in_executor", _fake_run_in_executor)
        monkeypatch.setattr(
            dengjen_grpc,
            "_reap_if_needed",
            lambda exe: calls.append(("reap_if_needed", exe)),
        )
        monkeypatch.setattr(
            dengjen_grpc,
            "start_grpc_server",
            lambda: (calls.append(("start", None)), False)[1],
        )

        with pytest.raises(RuntimeError):
            asyncio.run(dengjen_grpc.initialize())

        assert [c[0] for c in calls] == ["reap", "reap_if_needed", "start"]
        assert calls[1][1].endswith("dengjen-tts-grpc.exe")


class TestTerminateBoundedWait:
    """terminate() used to fire-and-forget GRPC_SERVER_PROCESS.terminate().
    It now waits up to PROCESS_EXIT_TIMEOUT, skips an already-dead process,
    and always clears the saved globalVars state on the way out."""

    def test_waits_for_the_process_to_exit_after_terminate(self, monkeypatch):
        waited = types.SimpleNamespace(timeout=None)
        fake_process = types.SimpleNamespace(
            poll=lambda: None,
            terminate=lambda: None,
            wait=lambda timeout=None: waited.__setattr__("timeout", timeout),
        )
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", fake_process)
        monkeypatch.setattr(dengjen_grpc, "close_channel", lambda: None)
        monkeypatch.setattr(dengjen_grpc.aio, "terminate", lambda: None)

        dengjen_grpc.terminate()

        assert waited.timeout == dengjen_grpc.PROCESS_EXIT_TIMEOUT
        assert dengjen_grpc.GRPC_SERVER_PROCESS is None

    def test_a_hung_process_logs_a_warning_instead_of_raising(self, monkeypatch):
        import subprocess

        def _wait(timeout=None):
            raise subprocess.TimeoutExpired(cmd="dengjen-tts-grpc.exe", timeout=timeout)

        fake_process = types.SimpleNamespace(
            poll=lambda: None, terminate=lambda: None, wait=_wait
        )
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", fake_process)
        monkeypatch.setattr(dengjen_grpc, "close_channel", lambda: None)
        monkeypatch.setattr(dengjen_grpc.aio, "terminate", lambda: None)

        dengjen_grpc.terminate()

        assert dengjen_grpc.GRPC_SERVER_PROCESS is None

    def test_skips_terminate_and_wait_for_an_already_dead_process(self, monkeypatch):
        calls = types.SimpleNamespace(terminate=False, wait=False)
        fake_process = types.SimpleNamespace(
            poll=lambda: 0,
            terminate=lambda: calls.__setattr__("terminate", True),
            wait=lambda timeout=None: calls.__setattr__("wait", True),
        )
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", fake_process)
        monkeypatch.setattr(dengjen_grpc, "close_channel", lambda: None)
        monkeypatch.setattr(dengjen_grpc.aio, "terminate", lambda: None)

        dengjen_grpc.terminate()

        assert not calls.terminate
        assert not calls.wait

    def test_clears_the_saved_globalvars_state(self, monkeypatch):
        import globalVars

        globalVars.DENGJEN_GRPC_SERVER_PORT = 1
        globalVars.GRPC_SERVER_PROCESS = object()
        monkeypatch.setattr(dengjen_grpc, "GRPC_SERVER_PROCESS", None)
        monkeypatch.setattr(dengjen_grpc, "close_channel", lambda: None)
        monkeypatch.setattr(dengjen_grpc.aio, "terminate", lambda: None)

        dengjen_grpc.terminate()

        assert not hasattr(globalVars, "DENGJEN_GRPC_SERVER_PORT")
        assert not hasattr(globalVars, "GRPC_SERVER_PROCESS")


class _FakeAioChannelForInitialize:
    def __init__(self):
        self._loop = None
        self.close_awaited = False
        self.target = None

    async def close(self):
        self.close_awaited = True


class TestInitializeChannelPortStaleness:
    """initialize()'s channel-reuse check used to look only at whether the
    aio loop matched, never at whether the port the channel was opened
    against was still the one start_grpc_server() just confirmed. #150
    made ports OS-assigned (a fresh spawn gets a different one each
    time), and _saved_server_is_alive()/start_grpc_server() can spawn a
    genuine replacement for a helper that died independently without
    start_grpc_server() itself touching CHANNEL -- so a stale channel
    could be kept pointed at a port nothing is listening on anymore.
    CHANNEL_PORT closes that gap."""

    @staticmethod
    def _run_initialize_with(monkeypatch, *, channel, channel_port, new_port):
        import asyncio

        created_channels = []

        def _create_channel(target):
            channel = _FakeAioChannelForInitialize()
            channel.target = target
            created_channels.append(channel)
            return channel

        async def _fake_run_in_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        async def _run():
            loop = asyncio.get_running_loop()
            channel._loop = loop
            monkeypatch.setattr(dengjen_grpc, "CHANNEL", channel)
            monkeypatch.setattr(dengjen_grpc, "CHANNEL_PORT", channel_port)
            monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVICE", "old-stub")
            # The confirmed port of the helper start_grpc_server() decided
            # to run with -- the same one whether it reused a live saved
            # process or just spawned a replacement.
            monkeypatch.setattr(dengjen_grpc, "DENGJEN_GRPC_SERVER_PORT", new_port)
            monkeypatch.setattr(dengjen_grpc, "start_grpc_server", lambda: True)
            monkeypatch.setattr(dengjen_grpc, "_reap_if_needed", lambda exe: None)
            monkeypatch.setattr(
                dengjen_grpc.aio, "run_in_executor", _fake_run_in_executor
            )
            monkeypatch.setattr(dengjen_grpc.aio.ENGINE, "event_loop", loop)
            monkeypatch.setattr(
                dengjen_grpc.grpc.aio, "insecure_channel", _create_channel
            )
            monkeypatch.setattr(
                dengjen_grpc, "DengjenGrpcStub", lambda channel: f"stub-for-{channel}"
            )

            await dengjen_grpc.initialize()

        asyncio.run(_run())
        return created_channels

    def test_rebuilds_the_channel_when_the_replacement_helper_gets_a_new_port(
        self, monkeypatch
    ):
        old_channel = _FakeAioChannelForInitialize()

        created_channels = self._run_initialize_with(
            monkeypatch, channel=old_channel, channel_port=50051, new_port=50052
        )

        assert old_channel.close_awaited
        assert len(created_channels) == 1
        assert created_channels[0].target == "localhost:50052"
        assert dengjen_grpc.CHANNEL is created_channels[0]
        assert dengjen_grpc.CHANNEL_PORT == 50052
        assert dengjen_grpc.DENGJEN_GRPC_SERVICE is not None
        assert dengjen_grpc.DENGJEN_GRPC_SERVICE != "old-stub"

    def test_reuses_the_channel_when_the_port_is_unchanged(self, monkeypatch):
        channel = _FakeAioChannelForInitialize()

        created_channels = self._run_initialize_with(
            monkeypatch, channel=channel, channel_port=50051, new_port=50051
        )

        assert created_channels == []
        assert not channel.close_awaited
        assert dengjen_grpc.CHANNEL is channel
        assert dengjen_grpc.CHANNEL_PORT == 50051
        assert dengjen_grpc.DENGJEN_GRPC_SERVICE == "old-stub"
