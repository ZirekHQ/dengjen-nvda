# coding: utf-8

import asyncio
import os
import threading
import typing as t
from concurrent.futures import CancelledError, ThreadPoolExecutor
from functools import wraps, partial
from logHandler import log
from .helpers import import_bundled_library



THREADED_EXECUTOR = None
ASYNCIO_EVENT_LOOP = asyncio.new_event_loop()
ASYNCIO_LOOP_THREAD = None
_STATE_LOCK = threading.RLock()
_LOOP_STARTED = threading.Event()


def initialize():
    global THREADED_EXECUTOR, ASYNCIO_EVENT_LOOP, ASYNCIO_LOOP_THREAD

    with _STATE_LOCK:
        if (
            ASYNCIO_LOOP_THREAD is not None
            and ASYNCIO_LOOP_THREAD.is_alive()
            and THREADED_EXECUTOR is not None
        ):
            loop_thread = ASYNCIO_LOOP_THREAD
        else:
            if ASYNCIO_EVENT_LOOP.is_closed():
                raise RuntimeError("The Sonata asyncio event loop was closed")
            if THREADED_EXECUTOR is None:
                THREADED_EXECUTOR = ThreadPoolExecutor(
                    max_workers=max(1, (os.cpu_count() or 2) // 2),
                    thread_name_prefix="sonata_nvda_executor",
                )

            def _thread_target():
                log.info("Starting Sonata asyncio event loop")
                asyncio.set_event_loop(ASYNCIO_EVENT_LOOP)
                ASYNCIO_EVENT_LOOP.call_soon(_LOOP_STARTED.set)
                try:
                    ASYNCIO_EVENT_LOOP.run_forever()
                finally:
                    _LOOP_STARTED.clear()

            _LOOP_STARTED.clear()
            ASYNCIO_LOOP_THREAD = threading.Thread(
                target=_thread_target,
                daemon=True,
                name="sonata_nvda_asyncio",
            )
            loop_thread = ASYNCIO_LOOP_THREAD
            loop_thread.start()

    if not _LOOP_STARTED.wait(timeout=5):
        raise RuntimeError("The Sonata asyncio event loop did not start")


def terminate():
    global THREADED_EXECUTOR, ASYNCIO_LOOP_THREAD, ASYNCIO_EVENT_LOOP
    with _STATE_LOCK:
        executor = THREADED_EXECUTOR
        loop_thread = ASYNCIO_LOOP_THREAD
        if loop_thread is not None and ASYNCIO_EVENT_LOOP.is_running():
            log.info("Shutting down Sonata asyncio event loop")
            ASYNCIO_EVENT_LOOP.call_soon_threadsafe(ASYNCIO_EVENT_LOOP.stop)

    if (
        loop_thread is not None
        and loop_thread is not threading.current_thread()
        and loop_thread.is_alive()
    ):
        loop_thread.join(timeout=5)
    if executor is not None:
        log.info("Shutting down the Sonata thread pool executor")
        executor.shutdown(wait=False, cancel_futures=True)

    with _STATE_LOCK:
        if ASYNCIO_LOOP_THREAD is loop_thread:
            ASYNCIO_LOOP_THREAD = None
        if THREADED_EXECUTOR is executor:
            THREADED_EXECUTOR = None


def asyncio_create_task(coro):
    initialize()
    return ASYNCIO_EVENT_LOOP.call_soon_threadsafe(ASYNCIO_EVENT_LOOP.create_task, coro)


def asyncio_cancel_task(task):
    if task is not None and ASYNCIO_EVENT_LOOP.is_running():
        ASYNCIO_EVENT_LOOP.call_soon_threadsafe(task.cancel)


def asyncio_coroutine_to_concurrent_future(async_func):
    """Returns a concurrent.futures.Future that wrapps the decorated async function."""

    @wraps(async_func)
    def wrapper(*args, **kwargs):
        initialize()
        return asyncio.run_coroutine_threadsafe(
            async_func(*args, **kwargs), loop=ASYNCIO_EVENT_LOOP
        )

    return wrapper


def call_threaded(func: t.Callable[..., None]) -> t.Callable[..., "Future"]:
    """Call `func` in a separate thread. It wraps the function
    in another function that returns a `concurrent.futures.Future`
    object when called.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            initialize()
            return THREADED_EXECUTOR.submit(func, *args, **kwargs)
        except RuntimeError:
            log.debug(f"Failed to submit function {func}.")

    return wrapper


def run_in_executor(func, *args, **kwargs):
    initialize()
    callable = partial(func, *args, **kwargs)
    return ASYNCIO_EVENT_LOOP.run_in_executor(THREADED_EXECUTOR, callable)
