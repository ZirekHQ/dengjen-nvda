# coding: utf-8
"""
Tests for aio module lifecycle resilience and re-initialization behavior.
"""

import os
import importlib.util
import pytest

_TESTS_DIR = os.path.dirname(__file__)
_AIO_PATH = os.path.join(
    _TESTS_DIR, "..", "addon", "synthDrivers", "sonata_neural_voices", "aio.py"
)


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

