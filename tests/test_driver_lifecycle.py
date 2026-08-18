# coding: utf-8
"""
Tests for aio module lifecycle resilience and re-initialization behavior.
"""

import ast
import asyncio
import gc
import os
import glob
import threading
import time
import types
import warnings
import importlib.util
from types import SimpleNamespace

_STRESS_THREADS = 8
_STRESS_ITERATIONS = 40

_TESTS_DIR = os.path.dirname(__file__)
_PKG_DIR = os.path.join(
    _TESTS_DIR, "..", "addon", "synthDrivers", "dengjen_neural_voices"
)
_AIO_PATH = os.path.join(_PKG_DIR, "aio.py")
_GRPC_CLIENT_PATH = os.path.join(_PKG_DIR, "grpc_client", "__init__.py")

_LOOP_THREAD_NAME = "piper4nvda_asyncio"


def _load_module_function(path, name, namespace):
    """Exec a single top-level function against a stubbed namespace.

    grpc_client imports grpc and NVDA globals, so it cannot be imported here.
    """
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    for node in ast.parse(source, filename=path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            exec(ast.get_source_segment(source, node), namespace)
            return namespace[name]
    raise LookupError(f"{name} not found in {path}")


class _FakeAioChannel:
    """Stands in for grpc.aio.Channel, whose close() is a coroutine."""

    def __init__(self):
        self.close_awaited = False
        self.closed_on_loop = None

    async def _close(self):
        self.close_awaited = True
        self.closed_on_loop = asyncio.get_running_loop()

    def close(self):
        return self._close()


def _never_awaited_warnings(caught):
    return [w for w in caught if "never awaited" in str(w.message)]


def _load_real_aio():
    spec = importlib.util.spec_from_file_location(
        "dengjen_neural_voices.aio_real", _AIO_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _package_sources():
    """(path, AST) for every first-party module, skipping vendored libraries."""
    for path in sorted(glob.glob(os.path.join(_PKG_DIR, "**", "*.py"), recursive=True)):
        if f"{os.sep}lib{os.sep}" in path:
            continue
        with open(path, "r", encoding="utf-8") as f:
            yield path, ast.parse(f.read(), filename=path)


def _top_level_names(tree):
    names = set()
    body = list(tree.body)
    for node in tree.body:
        if isinstance(node, ast.With):
            body.extend(node.body)
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.Assign):
            names.update(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


aio = _load_real_aio()


def _settled_loop_thread_count(timeout=2):
    """Loop-thread count once stopped threads have had a chance to exit."""
    deadline = time.monotonic() + timeout
    while True:
        count = len(
            [t for t in threading.enumerate() if t.name == _LOOP_THREAD_NAME]
        )
        if count <= 1 or time.monotonic() > deadline:
            return count
        time.sleep(0.05)


class TestAioLifecycle:

    def setup_method(self):
        aio.initialize()

    def teardown_method(self):
        aio.terminate()

    def test_initialize_is_idempotent(self):
        aio.initialize()
        aio.initialize()
        assert aio.ENGINE.event_loop is not None
        assert aio.ENGINE.event_loop.is_running()
        assert aio.ENGINE.executor is not None

    def test_reinitialization_after_terminate(self):
        # Shutdown loop and executor
        aio.terminate()
        assert aio.ENGINE.executor is None

        # Re-initialize
        aio.initialize()
        assert aio.ENGINE.event_loop is not None
        assert aio.ENGINE.event_loop.is_running()
        assert aio.ENGINE.executor is not None

    def test_asyncio_coroutine_to_concurrent_future_resurrects_stopped_loop(self):
        aio.terminate()

        @aio.asyncio_coroutine_to_concurrent_future
        async def dummy_coro():
            return 42

        fut = dummy_coro()
        assert fut.result(timeout=5) == 42

    def test_run_in_executor_resurrects_stopped_loop(self):
        aio.terminate()

        def sync_fn(val):
            return val * 2

        @aio.asyncio_coroutine_to_concurrent_future
        async def run_test():
            return await aio.run_in_executor(sync_fn, 21)

        fut = run_test()
        assert fut.result(timeout=5) == 42

    def test_task_creation_resolves_the_live_loop_after_reinitialization(self):
        aio.terminate()

        async def spoken():
            return "spoken"

        @aio.asyncio_coroutine_to_concurrent_future
        async def create_task_like_process_speech():
            loop = aio.asyncio.get_running_loop()
            assert loop is aio.ENGINE.event_loop
            return await loop.create_task(spoken())

        assert create_task_like_process_speech().result(timeout=5) == "spoken"

    def test_terminate_closes_and_clears_the_loop(self):
        loop = aio.ENGINE.event_loop
        assert loop is not None

        aio.terminate()

        assert loop.is_closed()
        assert aio.ENGINE.event_loop is None

    def test_repeated_cycles_do_not_accumulate_loop_threads(self):
        for _ in range(10):
            aio.terminate()
            aio.initialize()

        assert _settled_loop_thread_count() == 1

    def test_concurrent_ensure_running_does_not_orphan_loops(self):
        errors = []
        barrier = threading.Barrier(_STRESS_THREADS + 1)

        def worker():
            barrier.wait()
            for _ in range(_STRESS_ITERATIONS):
                try:
                    aio.ensure_running()
                except Exception as exc:
                    errors.append(repr(exc))
                    continue
                if aio.ENGINE.event_loop is None:
                    errors.append("ensure_running() left the event loop unset")

        threads = [threading.Thread(target=worker) for _ in range(_STRESS_THREADS)]
        for thread in threads:
            thread.start()

        barrier.wait()
        for _ in range(15):
            aio.terminate()
            time.sleep(0.01)
        for thread in threads:
            thread.join()

        aio.ensure_running()
        assert errors == []
        assert _settled_loop_thread_count() == 1


class TestAioGlobalsDoNotLeakMutableState:
    """Guards against re-introducing scattered mutable globals: the event
    loop/executor live on aio.ENGINE (a stable singleton whose properties
    are read fresh on every access), never as rebindable module-level
    names a caller could import by value and have go stale."""

    def test_the_old_scattered_globals_are_gone(self):
        assert not hasattr(aio, "ASYNCIO_EVENT_LOOP")
        assert not hasattr(aio, "THREADED_EXECUTOR")
        assert not hasattr(aio, "ASYNCIO_LOOP_THREAD")
        assert not hasattr(aio, "EXECUTOR_IS_SHUTDOWN")

    def test_no_module_imports_a_loop_or_executor_by_value_from_aio(self):
        offenders = []
        for path, tree in _package_sources():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level == 0:
                    continue
                if (node.module or "").split(".")[-1] != "aio":
                    continue
                for alias in node.names:
                    name = alias.name
                    # UPPER_CASE only: aio's helper functions (run_in_executor,
                    # etc.) also contain "loop"/"executor" but are stable
                    # function references, not mutable state.
                    if name.isupper() and ("LOOP" in name or "EXECUTOR" in name):
                        offenders.append(f"{os.path.basename(path)}: {name}")

        assert offenders == [], (
            f"{offenders} import loop/executor state by value from aio; read "
            "aio.ENGINE.event_loop / aio.ENGINE.executor fresh instead, or use "
            "asyncio.get_running_loop()."
        )


class TestGrpcChannelTeardown:

    def setup_method(self):
        aio.initialize()

    def teardown_method(self):
        aio.terminate()

    def _close_channel_with(self, channel):
        namespace = {
            "asyncio": asyncio,
            "aio": aio,
            "log": types.SimpleNamespace(debug=lambda *a, **k: None),
            "CHANNEL": channel,
            "CHANNEL_CLOSE_TIMEOUT": 5,
        }
        close_channel = _load_module_function(
            _GRPC_CLIENT_PATH, "close_channel", namespace
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            close_channel()
            gc.collect()
        return namespace, caught

    def test_dropping_the_close_coroutine_is_detectable(self):
        """Self-check: the assertions below are only meaningful if this warns."""
        channel = _FakeAioChannel()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            channel.close()
            gc.collect()

        assert _never_awaited_warnings(caught)

    def test_close_channel_awaits_close_on_the_owning_loop(self):
        channel = _FakeAioChannel()
        namespace, caught = self._close_channel_with(channel)

        assert channel.close_awaited
        assert channel.closed_on_loop is aio.ENGINE.event_loop
        assert namespace["CHANNEL"] is None
        assert _never_awaited_warnings(caught) == []

    def test_close_channel_discards_coroutine_when_loop_is_gone(self):
        aio.terminate()
        channel = _FakeAioChannel()
        namespace, caught = self._close_channel_with(channel)

        assert not channel.close_awaited
        assert namespace["CHANNEL"] is None
        assert _never_awaited_warnings(caught) == []


class TestCrossModuleAttributesResolve:
    """__init__.py cannot be imported without NVDA, so check its references statically."""

    def test_grpc_client_attribute_references_are_defined(self):
        sources = dict(_package_sources())
        grpc_client_path = os.path.join(_PKG_DIR, "grpc_client", "__init__.py")
        defined = _top_level_names(sources[grpc_client_path])

        unresolved = []
        for path, tree in sources.items():
            if path == grpc_client_path:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "grpc_client"
                    and node.attr not in defined
                ):
                    unresolved.append(
                        f"{os.path.basename(path)}:{node.lineno} grpc_client.{node.attr}"
                    )

        assert unresolved == [], (
            f"{unresolved} reference names that grpc_client does not define at module "
            "level; these fail at runtime only, since NVDA-only modules are not importable."
        )


class _FakeProcess:
    def __init__(self, pid, exe, *, survives_terminate=False):
        self.info = {"pid": pid, "exe": exe}
        self.survives_terminate = survives_terminate
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class _FakePsutil:
    class AccessDenied(Exception):
        pass

    class NoSuchProcess(Exception):
        pass

    def __init__(self, processes):
        self.processes = processes
        self.wait_calls = []

    def process_iter(self, attrs):
        assert attrs == ["pid", "exe"]
        return iter(self.processes)

    def wait_procs(self, processes, timeout):
        processes = list(processes)
        self.wait_calls.append((processes, timeout))
        alive = [p for p in processes if p.survives_terminate and not p.killed]
        return [p for p in processes if p not in alive], alive


class TestGrpcServerProcessLifecycle:
    def _load_reaper(self, processes, *, current_pid=100):
        fake_psutil = _FakePsutil(processes)
        messages = []
        namespace = {
            "os": SimpleNamespace(
                getpid=lambda: current_pid,
                path=os.path,
            ),
            "psutil": fake_psutil,
            "log": SimpleNamespace(info=messages.append),
            "PROCESS_EXIT_TIMEOUT": 3,
        }
        reaper = _load_module_function(
            _GRPC_CLIENT_PATH, "_reap_stale_grpc_servers", namespace
        )
        return reaper, fake_psutil, messages

    def test_reaper_only_stops_helpers_from_this_addon_copy(self, tmp_path):
        expected = str(tmp_path / "addon" / "sonata-grpc.exe")
        ours = _FakeProcess(1, expected)
        another_copy = _FakeProcess(2, str(tmp_path / "portable" / "sonata-grpc.exe"))
        current = _FakeProcess(100, expected)
        reaper, fake_psutil, messages = self._load_reaper(
            [ours, another_copy, current]
        )

        reaper(expected)

        assert ours.terminated
        assert not another_copy.terminated
        assert not current.terminated
        assert len(fake_psutil.wait_calls) == 1
        assert messages == ["Removed 1 abandoned Dengjen GRPC helper process(es)"]

    def test_reaper_force_kills_a_helper_that_will_not_exit(self, tmp_path):
        expected = str(tmp_path / "sonata-grpc.exe")
        stuck = _FakeProcess(1, expected, survives_terminate=True)
        reaper, _, _ = self._load_reaper([stuck])

        reaper(expected)

        assert stuck.terminated
        assert stuck.killed

    def test_clear_saved_state_removes_both_global_values(self):
        saved_state = SimpleNamespace(
            SONATA_GRPC_SERVER_PORT=12345,
            GRPC_SERVER_PROCESS=object(),
            unrelated="preserved",
        )
        namespace = {"globalVars": saved_state}
        clear_state = _load_module_function(
            _GRPC_CLIENT_PATH, "_clear_saved_server_state", namespace
        )

        clear_state()

        assert not hasattr(saved_state, "SONATA_GRPC_SERVER_PORT")
        assert not hasattr(saved_state, "GRPC_SERVER_PROCESS")
        assert saved_state.unrelated == "preserved"

