import asyncio
import os
import threading
import typing as t
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from functools import partial, wraps

from logHandler import log

__all__ = ["CancelledError"]

LOOP_STARTUP_TIMEOUT = 5
LOOP_SHUTDOWN_TIMEOUT = 2


def _close_loop(loop):
    if loop is None or loop.is_closed() or loop.is_running():
        return
    try:
        loop.close()
    except RuntimeError:
        log.debug("Failed to close the asyncio event loop", exc_info=True)


class AsyncEngine:
    """Owns the thread pool executor and asyncio event loop the synth driver
    runs its gRPC and audio work on.

    `ENGINE` below is the module's singleton, used by the driver at runtime;
    tests construct their own instances to exercise the lifecycle without
    fighting shared process-wide state.
    """

    def __init__(self):
        self._lifecycle_lock = threading.RLock()
        self._loop_running = threading.Event()
        self._executor = None
        self._event_loop = None
        self._loop_thread = None
        self._executor_is_shutdown = False

    @property
    def executor(self):
        return self._executor

    @property
    def event_loop(self):
        return self._event_loop

    @property
    def loop_thread(self):
        return self._loop_thread

    def is_running(self):
        return (
            self._executor is not None
            and not self._executor_is_shutdown
            and self._loop_thread is not None
            and self._loop_thread.is_alive()
            and self._event_loop is not None
            and self._event_loop.is_running()
        )

    def initialize(self):
        with self._lifecycle_lock:
            if self._executor is None or self._executor_is_shutdown:
                max_workers = max(1, (os.cpu_count() or 2) // 2)
                self._executor = ThreadPoolExecutor(
                    max_workers=max_workers, thread_name_prefix="piper4nvda_executor"
                )
                self._executor_is_shutdown = False

            if self._loop_thread is not None and self._loop_thread.is_alive():
                if (
                    self._loop_running.wait(timeout=LOOP_SHUTDOWN_TIMEOUT)
                    and self.is_running()
                ):
                    return
                self._loop_thread.join(timeout=LOOP_SHUTDOWN_TIMEOUT)

            _close_loop(self._event_loop)
            self._event_loop = asyncio.new_event_loop()
            self._loop_running.clear()

            def _thread_target(loop):
                log.info("Starting asyncio event loop")
                asyncio.set_event_loop(loop)
                loop.call_soon(self._loop_running.set)
                try:
                    loop.run_forever()
                finally:
                    self._loop_running.clear()

            self._loop_thread = threading.Thread(
                target=_thread_target,
                args=(self._event_loop,),
                daemon=True,
                name="piper4nvda_asyncio",
            )
            self._loop_thread.start()
            if not self._loop_running.wait(timeout=LOOP_STARTUP_TIMEOUT):
                log.error("Timed out waiting for the asyncio event loop to start")

    def ensure_running(self):
        if self.is_running():
            return
        with self._lifecycle_lock:
            if not self.is_running():
                self.initialize()

    def terminate(self):
        with self._lifecycle_lock:
            log.info("Shutting down the thread pool executor")
            if self._executor is not None:
                self._executor.shutdown(wait=False)
                self._executor = None
            self._executor_is_shutdown = True
            if self._loop_thread is not None and self._loop_thread.is_alive():
                log.info("Shutting down asyncio event loop")
                loop_thread = self._loop_thread
                self._loop_thread = None
                if self._event_loop is not None and self._event_loop.is_running():
                    self._event_loop.call_soon_threadsafe(self._event_loop.stop)
                loop_thread.join(timeout=LOOP_SHUTDOWN_TIMEOUT)
            self._loop_running.clear()
            _close_loop(self._event_loop)
            self._event_loop = None

    def create_task(self, coro):
        self.ensure_running()
        with self._lifecycle_lock:
            loop = self._event_loop
            if loop is None or not loop.is_running():
                coro.close()
                raise RuntimeError("AsyncEngine event loop is not running")
            return asyncio.run_coroutine_threadsafe(coro, loop)

    def cancel_task(self, task):
        if self._event_loop is not None and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(task.cancel)

    def coroutine_to_concurrent_future(self, async_func):
        """Returns a concurrent.futures.Future that wraps the decorated async function."""

        @wraps(async_func)
        def wrapper(*args, **kwargs):
            self.ensure_running()
            return asyncio.run_coroutine_threadsafe(
                async_func(*args, **kwargs), loop=self._event_loop
            )

        return wrapper

    def call_threaded(self, func: t.Callable[..., None]) -> t.Callable[..., "Future"]:
        """Call `func` in a separate thread. It wraps the function
        in another function that returns a `concurrent.futures.Future`
        object when called.
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            self.ensure_running()
            try:
                return self._executor.submit(func, *args, **kwargs)
            except RuntimeError:
                log.debug(f"Failed to submit function {func}.")

        return wrapper

    def run_in_executor(self, func, *args, **kwargs):
        self.ensure_running()
        bound_func = partial(func, *args, **kwargs)
        return self._event_loop.run_in_executor(self._executor, bound_func)


ENGINE = AsyncEngine()


def initialize():
    ENGINE.initialize()


def ensure_running():
    ENGINE.ensure_running()


def terminate():
    ENGINE.terminate()


def asyncio_create_task(coro):
    return ENGINE.create_task(coro)


def asyncio_cancel_task(task):
    ENGINE.cancel_task(task)


def asyncio_coroutine_to_concurrent_future(async_func):
    return ENGINE.coroutine_to_concurrent_future(async_func)


def call_threaded(func: t.Callable[..., None]) -> t.Callable[..., "Future"]:
    return ENGINE.call_threaded(func)


def run_in_executor(func, *args, **kwargs):
    return ENGINE.run_in_executor(func, *args, **kwargs)
