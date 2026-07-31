# coding: utf-8
"""
Tests for aio module lifecycle resilience and re-initialization behavior.
"""

import ast
import os
import glob
import threading
import time
import importlib.util

_STRESS_THREADS = 8
_STRESS_ITERATIONS = 40

_TESTS_DIR = os.path.dirname(__file__)
_PKG_DIR = os.path.join(
    _TESTS_DIR, "..", "addon", "synthDrivers", "sonata_neural_voices"
)
_AIO_PATH = os.path.join(_PKG_DIR, "aio.py")

_LOOP_THREAD_NAME = "piper4nvda_asyncio"


def _load_real_aio():
    spec = importlib.util.spec_from_file_location(
        "sonata_neural_voices.aio_real", _AIO_PATH
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
        assert aio.ASYNCIO_EVENT_LOOP is not None
        assert aio.ASYNCIO_EVENT_LOOP.is_running()
        assert aio.THREADED_EXECUTOR is not None

    def test_reinitialization_after_terminate(self):
        # Shutdown loop and executor
        aio.terminate()
        assert aio.THREADED_EXECUTOR is None

        # Re-initialize
        aio.initialize()
        assert aio.ASYNCIO_EVENT_LOOP is not None
        assert aio.ASYNCIO_EVENT_LOOP.is_running()
        assert aio.THREADED_EXECUTOR is not None

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
            assert loop is aio.ASYNCIO_EVENT_LOOP
            return await loop.create_task(spoken())

        assert create_task_like_process_speech().result(timeout=5) == "spoken"

    def test_terminate_closes_and_clears_the_loop(self):
        loop = aio.ASYNCIO_EVENT_LOOP
        assert loop is not None

        aio.terminate()

        assert loop.is_closed()
        assert aio.ASYNCIO_EVENT_LOOP is None

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
                if aio.ASYNCIO_EVENT_LOOP is None:
                    errors.append("ensure_running() left ASYNCIO_EVENT_LOOP unset")

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


class TestAioGlobalsAreNotAliased:
    """Guards against re-introducing a stale by-value import of a mutable aio global."""

    def test_no_module_imports_the_event_loop_by_value(self):
        offenders = []
        for path, tree in _package_sources():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level == 0:
                    continue
                if (node.module or "").split(".")[-1] != "aio":
                    continue
                for alias in node.names:
                    if alias.name == "ASYNCIO_EVENT_LOOP":
                        offenders.append(os.path.basename(path))

        assert offenders == [], (
            f"{offenders} import ASYNCIO_EVENT_LOOP by value; the alias goes stale once "
            "aio.initialize() rebinds the loop. Reference aio.ASYNCIO_EVENT_LOOP or "
            "asyncio.get_running_loop() instead."
        )


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

