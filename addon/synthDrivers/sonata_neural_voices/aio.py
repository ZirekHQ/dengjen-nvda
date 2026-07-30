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
ASYNCIO_EVENT_LOOP = None
ASYNCIO_LOOP_THREAD = None


def initialize():
    global THREADED_EXECUTOR, ASYNCIO_EVENT_LOOP, ASYNCIO_LOOP_THREAD

    if THREADED_EXECUTOR is None or getattr(THREADED_EXECUTOR, "_shutdown", False):
        max_workers = max(1, (os.cpu_count() or 2) // 2)
        THREADED_EXECUTOR = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="piper4nvda_executor"
        )

    if ASYNCIO_LOOP_THREAD is not None and ASYNCIO_LOOP_THREAD.is_alive():
        if ASYNCIO_EVENT_LOOP is not None and ASYNCIO_EVENT_LOOP.is_running():
            return
        ASYNCIO_LOOP_THREAD.join(timeout=2)

    ASYNCIO_EVENT_LOOP = asyncio.new_event_loop()

    def _thread_target(loop):
        log.info("Starting asyncio event loop")
        asyncio.set_event_loop(loop)
        loop.run_forever()

    ASYNCIO_LOOP_THREAD = threading.Thread(
        target=_thread_target, args=(ASYNCIO_EVENT_LOOP,), daemon=True, name="piper4nvda_asyncio"
    )
    ASYNCIO_LOOP_THREAD.start()


def ensure_running():
    if (
        THREADED_EXECUTOR is None
        or getattr(THREADED_EXECUTOR, "_shutdown", False)
        or ASYNCIO_LOOP_THREAD is None
        or not ASYNCIO_LOOP_THREAD.is_alive()
        or ASYNCIO_EVENT_LOOP is None
        or not ASYNCIO_EVENT_LOOP.is_running()
    ):
        initialize()


def terminate():
    global THREADED_EXECUTOR, ASYNCIO_LOOP_THREAD, ASYNCIO_EVENT_LOOP
    log.info("Shutting down the thread pool executor")
    if THREADED_EXECUTOR is not None:
        THREADED_EXECUTOR.shutdown(wait=False)
        THREADED_EXECUTOR = None
    if ASYNCIO_LOOP_THREAD is not None and ASYNCIO_LOOP_THREAD.is_alive():
        log.info("Shutting down asyncio event loop")
        loop_thread = ASYNCIO_LOOP_THREAD
        ASYNCIO_LOOP_THREAD = None
        if ASYNCIO_EVENT_LOOP is not None and ASYNCIO_EVENT_LOOP.is_running():
            ASYNCIO_EVENT_LOOP.call_soon_threadsafe(ASYNCIO_EVENT_LOOP.stop)
        loop_thread.join(timeout=2)



def asyncio_create_task(coro):
    ensure_running()
    return ASYNCIO_EVENT_LOOP.call_soon_threadsafe(ASYNCIO_EVENT_LOOP.create_task, coro)


def asyncio_cancel_task(task):
    if ASYNCIO_EVENT_LOOP is not None and ASYNCIO_EVENT_LOOP.is_running():
        ASYNCIO_EVENT_LOOP.call_soon_threadsafe(task.cancel)


def asyncio_coroutine_to_concurrent_future(async_func):
    """Returns a concurrent.futures.Future that wraps the decorated async function."""

    @wraps(async_func)
    def wrapper(*args, **kwargs):
        ensure_running()
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
        ensure_running()
        try:
            return THREADED_EXECUTOR.submit(func, *args, **kwargs)
        except RuntimeError:
            log.debug(f"Failed to submit function {func}.")

    return wrapper


def run_in_executor(func, *args, **kwargs):
    ensure_running()
    bound_func = partial(func, *args, **kwargs)
    return ASYNCIO_EVENT_LOOP.run_in_executor(THREADED_EXECUTOR, bound_func)
