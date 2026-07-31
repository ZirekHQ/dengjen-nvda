# coding: utf-8
"""
Tests for aio.py — the thread pool and asyncio event loop the synth driver
runs all of its gRPC and audio work on.

Loaded under a private module name so the `sonata_neural_voices.aio` stub that
conftest installs for tts_system stays in place.
"""

import asyncio
import concurrent.futures
import os
import threading

import pytest

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

aio = load_module_from_path(
    "sonata_neural_voices._aio_under_test",
    os.path.join(SYNTH_PKG_DIR, "aio.py"),
    package="sonata_neural_voices",
)


@pytest.fixture(scope="module")
def running_aio():
    aio.initialize()
    yield aio
    # TestTerminate shuts things down itself, so only tear down if it has not.
    if aio.THREADED_EXECUTOR is not None:
        aio.terminate()


class TestInitialize:
    def test_creates_executor_and_loop_thread(self, running_aio):
        assert running_aio.THREADED_EXECUTOR is not None
        assert running_aio.ASYNCIO_LOOP_THREAD is not None

    def test_loop_thread_is_daemon_so_nvda_can_exit(self, running_aio):
        assert running_aio.ASYNCIO_LOOP_THREAD.daemon is True

    def test_loop_thread_is_alive_and_running(self, running_aio):
        assert running_aio.ASYNCIO_LOOP_THREAD.is_alive()
        assert running_aio.ASYNCIO_EVENT_LOOP.is_running()

    def test_reinitialize_keeps_the_existing_loop_thread(self, running_aio):
        thread = running_aio.ASYNCIO_LOOP_THREAD
        running_aio.initialize()
        assert running_aio.ASYNCIO_LOOP_THREAD is thread


class TestCoroutineToConcurrentFuture:
    def test_returns_a_concurrent_future_carrying_the_result(self, running_aio):
        @running_aio.asyncio_coroutine_to_concurrent_future
        async def add(a, b):
            return a + b

        future = add(2, 3)
        assert isinstance(future, concurrent.futures.Future)
        assert future.result(timeout=5) == 5

    def test_propagates_exceptions_to_the_future(self, running_aio):
        @running_aio.asyncio_coroutine_to_concurrent_future
        async def boom():
            raise ValueError("nope")

        future = boom()
        with pytest.raises(ValueError, match="nope"):
            future.result(timeout=5)

    def test_preserves_the_wrapped_function_metadata(self, running_aio):
        @running_aio.asyncio_coroutine_to_concurrent_future
        async def documented():
            """A docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "A docstring."


class TestCallThreaded:
    def test_submits_to_the_executor_and_returns_a_future(self, running_aio):
        @running_aio.call_threaded
        def double(value):
            return value * 2

        future = double(21)
        assert isinstance(future, concurrent.futures.Future)
        assert future.result(timeout=5) == 42

    def test_runs_off_the_calling_thread(self, running_aio):
        @running_aio.call_threaded
        def which_thread():
            return threading.current_thread().name

        name = which_thread().result(timeout=5)
        assert name != threading.current_thread().name
        assert name.startswith("piper4nvda_executor")

    def test_preserves_the_wrapped_function_metadata(self, running_aio):
        @running_aio.call_threaded
        def documented():
            """Another docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "Another docstring."


class TestRunInExecutor:
    def test_awaits_a_sync_function_from_inside_the_loop(self, running_aio):
        recorded = []

        async def drive():
            return await running_aio.run_in_executor(recorded.append, "value")

        asyncio.run_coroutine_threadsafe(
            drive(), running_aio.ASYNCIO_EVENT_LOOP
        ).result(timeout=5)
        assert recorded == ["value"]

    def test_passes_through_keyword_arguments(self, running_aio):
        def join(a, b="default"):
            return f"{a}-{b}"

        async def drive():
            return await running_aio.run_in_executor(join, "x", b="y")

        result = asyncio.run_coroutine_threadsafe(
            drive(), running_aio.ASYNCIO_EVENT_LOOP
        ).result(timeout=5)
        assert result == "x-y"


class TestAsyncioTaskHelpers:
    def test_create_task_schedules_the_coroutine(self, running_aio):
        ran = threading.Event()

        async def mark():
            ran.set()

        running_aio.asyncio_create_task(mark())
        assert ran.wait(timeout=5)

    def test_cancel_task_cancels_a_pending_task(self, running_aio):
        loop = running_aio.ASYNCIO_EVENT_LOOP

        async def make_task():
            return loop.create_task(asyncio.sleep(30))

        task = asyncio.run_coroutine_threadsafe(make_task(), loop).result(timeout=5)
        running_aio.asyncio_cancel_task(task)

        async def await_it():
            try:
                await task
            except asyncio.CancelledError:
                return "cancelled"
            return "completed"

        outcome = asyncio.run_coroutine_threadsafe(await_it(), loop).result(timeout=5)
        assert outcome == "cancelled"


class TestTerminate:
    def test_clears_the_executor_and_the_loop_thread(self, running_aio):
        assert running_aio.THREADED_EXECUTOR is not None
        running_aio.terminate()
        assert running_aio.THREADED_EXECUTOR is None
        assert running_aio.ASYNCIO_LOOP_THREAD is None
