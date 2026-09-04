"""
Tests for aio.AsyncEngine — the class that owns the thread pool executor and
asyncio event loop the synth driver runs its gRPC and audio work on.

Written before AsyncEngine existed (TDD): each test builds its own instance
rather than sharing module-level state, which is the point of extracting
this out of module globals in the first place — the lifecycle can be
exercised in isolation instead of fighting shared process-wide state.

Loaded under a private module name so the `dengjen_neural_voices.aio` stub
that conftest installs for tts_system stays in place.
"""

import asyncio
import concurrent.futures
import os
import threading
from unittest.mock import MagicMock

import pytest

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

aio = load_module_from_path(
    "dengjen_neural_voices._async_engine_under_test",
    os.path.join(SYNTH_PKG_DIR, "aio.py"),
    package="dengjen_neural_voices",
)


@pytest.fixture
def engine():
    e = aio.AsyncEngine()
    yield e
    e.terminate()


@pytest.fixture
def running_engine(engine):
    engine.initialize()
    return engine


class TestConstruction:
    def test_starts_with_no_executor(self, engine):
        assert engine.executor is None

    def test_starts_with_no_event_loop(self, engine):
        assert engine.event_loop is None

    def test_starts_with_no_loop_thread(self, engine):
        assert engine.loop_thread is None

    def test_starts_not_running(self, engine):
        assert engine.is_running() is False

    def test_two_instances_do_not_share_state(self, engine):
        other = aio.AsyncEngine()
        try:
            other.initialize()
            assert engine.executor is None
            assert engine.event_loop is None
        finally:
            other.terminate()


class TestInitialize:
    def test_creates_an_executor(self, running_engine):
        assert running_engine.executor is not None

    def test_creates_a_loop_thread(self, running_engine):
        assert running_engine.loop_thread is not None

    def test_loop_thread_is_daemon_so_nvda_can_exit(self, running_engine):
        assert running_engine.loop_thread.daemon is True

    def test_loop_thread_is_alive_and_running(self, running_engine):
        assert running_engine.loop_thread.is_alive()
        assert running_engine.event_loop.is_running()

    def test_is_running_reports_true_once_initialized(self, running_engine):
        assert running_engine.is_running() is True

    def test_reinitialize_keeps_the_existing_loop_thread(self, running_engine):
        thread = running_engine.loop_thread
        running_engine.initialize()
        assert running_engine.loop_thread is thread


class TestEnsureRunning:
    def test_starts_the_engine_when_not_running(self, engine):
        engine.ensure_running()
        assert engine.is_running() is True

    def test_is_a_no_op_when_already_running(self, running_engine):
        thread = running_engine.loop_thread
        running_engine.ensure_running()
        assert running_engine.loop_thread is thread


class TestCoroutineToConcurrentFuture:
    def test_returns_a_concurrent_future_carrying_the_result(self, running_engine):
        @running_engine.coroutine_to_concurrent_future
        async def add(a, b):
            return a + b

        future = add(2, 3)
        assert isinstance(future, concurrent.futures.Future)
        assert future.result(timeout=5) == 5

    def test_propagates_exceptions_to_the_future(self, running_engine):
        @running_engine.coroutine_to_concurrent_future
        async def boom():
            raise ValueError("nope")

        future = boom()
        with pytest.raises(ValueError, match="nope"):
            future.result(timeout=5)

    def test_preserves_the_wrapped_function_metadata(self, running_engine):
        @running_engine.coroutine_to_concurrent_future
        async def documented():
            """A docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "A docstring."

    def test_resurrects_a_terminated_engine(self, running_engine):
        running_engine.terminate()

        @running_engine.coroutine_to_concurrent_future
        async def dummy():
            return 42

        assert dummy().result(timeout=5) == 42


class TestCallThreaded:
    def test_submits_to_the_executor_and_returns_a_future(self, running_engine):
        @running_engine.call_threaded
        def double(value):
            return value * 2

        future = double(21)
        assert isinstance(future, concurrent.futures.Future)
        assert future.result(timeout=5) == 42

    def test_runs_off_the_calling_thread(self, running_engine):
        @running_engine.call_threaded
        def which_thread():
            return threading.current_thread().name

        name = which_thread().result(timeout=5)
        assert name != threading.current_thread().name
        assert name.startswith("piper4nvda_executor")

    def test_preserves_the_wrapped_function_metadata(self, running_engine):
        @running_engine.call_threaded
        def documented():
            """Another docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "Another docstring."


class TestRunInExecutor:
    def test_awaits_a_sync_function_from_inside_the_loop(self, running_engine):
        recorded = []

        async def drive():
            return await running_engine.run_in_executor(recorded.append, "value")

        asyncio.run_coroutine_threadsafe(drive(), running_engine.event_loop).result(
            timeout=5
        )
        assert recorded == ["value"]

    def test_passes_through_keyword_arguments(self, running_engine):
        def join(a, b="default"):
            return f"{a}-{b}"

        async def drive():
            return await running_engine.run_in_executor(join, "x", b="y")

        result = asyncio.run_coroutine_threadsafe(
            drive(), running_engine.event_loop
        ).result(timeout=5)
        assert result == "x-y"


class TestTaskHelpers:
    def test_create_task_schedules_the_coroutine(self, running_engine):
        ran = threading.Event()

        async def mark():
            ran.set()

        running_engine.create_task(mark())
        assert ran.wait(timeout=5)

    def test_cancel_task_cancels_a_pending_task(self, running_engine):
        loop = running_engine.event_loop

        async def make_task():
            return loop.create_task(asyncio.sleep(30))

        task = asyncio.run_coroutine_threadsafe(make_task(), loop).result(timeout=5)
        running_engine.cancel_task(task)

        async def await_it():
            try:
                await task
            except asyncio.CancelledError:
                return "cancelled"
            return "completed"

        outcome = asyncio.run_coroutine_threadsafe(await_it(), loop).result(timeout=5)
        assert outcome == "cancelled"

    def test_create_task_closes_the_coroutine_when_the_loop_is_gone(
        self, engine, monkeypatch
    ):
        # Simulates the create_task/terminate race: ensure_running() has
        # already returned (stubbed here to a no-op, since this engine was
        # never actually started -- no real thread to leak) but _event_loop
        # is unset, exactly what a concurrent terminate() would leave behind
        # between create_task's ensure_running() call and it reading the
        # loop under the lifecycle lock. The coroutine must be closed rather
        # than left to leak as a "was never awaited" warning.
        monkeypatch.setattr(engine, "ensure_running", lambda: None)
        fake_coro = MagicMock()

        with pytest.raises(RuntimeError):
            engine.create_task(fake_coro)

        fake_coro.close.assert_called_once()


class TestTerminate:
    def test_clears_the_executor(self, running_engine):
        running_engine.terminate()
        assert running_engine.executor is None

    def test_clears_the_loop_thread(self, running_engine):
        running_engine.terminate()
        assert running_engine.loop_thread is None

    def test_closes_and_clears_the_event_loop(self, running_engine):
        loop = running_engine.event_loop
        running_engine.terminate()
        assert loop.is_closed()
        assert running_engine.event_loop is None

    def test_is_running_reports_false_after_terminate(self, running_engine):
        running_engine.terminate()
        assert running_engine.is_running() is False


class TestModuleLevelDelegation:
    """The module-level functions (aio.initialize(), aio.ensure_running(), etc.)
    stay the public API __init__.py imports by name; they should just proxy
    to the module singleton aio.ENGINE."""

    @pytest.fixture(autouse=True)
    def _terminate_singleton_after(self):
        yield
        aio.ENGINE.terminate()

    def test_engine_singleton_exists(self):
        assert isinstance(aio.ENGINE, aio.AsyncEngine)

    def test_initialize_starts_the_singleton(self):
        aio.initialize()
        assert aio.ENGINE.is_running() is True

    def test_ensure_running_starts_the_singleton(self):
        aio.ensure_running()
        assert aio.ENGINE.is_running() is True

    def test_terminate_stops_the_singleton(self):
        aio.initialize()
        aio.terminate()
        assert aio.ENGINE.is_running() is False

    def test_run_in_executor_uses_the_singleton(self):
        recorded = []

        async def drive():
            return await aio.run_in_executor(recorded.append, "value")

        aio.initialize()
        asyncio.run_coroutine_threadsafe(drive(), aio.ENGINE.event_loop).result(
            timeout=5
        )
        assert recorded == ["value"]

    def test_asyncio_coroutine_to_concurrent_future_uses_the_singleton(self):
        @aio.asyncio_coroutine_to_concurrent_future
        async def add(a, b):
            return a + b

        assert add(2, 3).result(timeout=5) == 5

    def test_asyncio_create_task_uses_the_singleton(self):
        ran = threading.Event()

        async def mark():
            ran.set()

        aio.asyncio_create_task(mark())
        assert ran.wait(timeout=5)

    def test_asyncio_cancel_task_uses_the_singleton(self):
        aio.initialize()
        loop = aio.ENGINE.event_loop

        async def make_task():
            return loop.create_task(asyncio.sleep(30))

        task = asyncio.run_coroutine_threadsafe(make_task(), loop).result(timeout=5)
        aio.asyncio_cancel_task(task)

        async def await_it():
            try:
                await task
            except asyncio.CancelledError:
                return "cancelled"
            return "completed"

        outcome = asyncio.run_coroutine_threadsafe(await_it(), loop).result(timeout=5)
        assert outcome == "cancelled"

    def test_call_threaded_uses_the_singleton(self):
        @aio.call_threaded
        def double(value):
            return value * 2

        assert double(21).result(timeout=5) == 42
