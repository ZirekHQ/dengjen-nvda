# coding: utf-8
"""
Tests for aio module lifecycle resilience and re-initialization behavior.
"""

import ast
import os
import glob
import threading
import importlib.util

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


aio = _load_real_aio()


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

        live = [t for t in threading.enumerate() if t.name == _LOOP_THREAD_NAME]
        assert len(live) == 1


class TestAioGlobalsAreNotAliased:
    """Guards against re-introducing a stale by-value import of a mutable aio global."""

    def test_no_module_imports_the_event_loop_by_value(self):
        offenders = []
        for path in glob.glob(os.path.join(_PKG_DIR, "**", "*.py"), recursive=True):
            if f"{os.sep}lib{os.sep}" in path:
                continue
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
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

