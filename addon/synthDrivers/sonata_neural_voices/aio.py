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
EXECUTOR_IS_SHUTDOWN = False

LOOP_STARTUP_TIMEOUT = 5
LOOP_SHUTDOWN_TIMEOUT = 2

_LIFECYCLE_LOCK = threading.RLock()
_LOOP_RUNNING = threading.Event()


def _close_loop(loop):
    if loop is None or loop.is_closed() or loop.is_running():
        return
    try:
        loop.close()
    except RuntimeError:
        log.debug("Failed to close the asyncio event loop", exc_info=True)


def _is_running():
    return (
        THREADED_EXECUTOR is not None
        and not EXECUTOR_IS_SHUTDOWN
        and ASYNCIO_LOOP_THREAD is not None
        and ASYNCIO_LOOP_THREAD.is_alive()
        and ASYNCIO_EVENT_LOOP is not None
        and ASYNCIO_EVENT_LOOP.is_running()
    )


def initialize():
    global THREADED_EXECUTOR, ASYNCIO_EVENT_LOOP, ASYNCIO_LOOP_THREAD
    global EXECUTOR_IS_SHUTDOWN

    with _LIFECYCLE_LOCK:
        if THREADED_EXECUTOR is None or EXECUTOR_IS_SHUTDOWN:
            max_workers = max(1, (os.cpu_count() or 2) // 2)
            THREADED_EXECUTOR = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="piper4nvda_executor"
            )
            EXECUTOR_IS_SHUTDOWN = False

        if ASYNCIO_LOOP_THREAD is not None and ASYNCIO_LOOP_THREAD.is_alive():
            # The thread is started before run_forever() marks the loop running,
            # so wait on the handshake rather than sampling is_running().
            if _LOOP_RUNNING.wait(timeout=LOOP_SHUTDOWN_TIMEOUT) and _is_running():
                return
            ASYNCIO_LOOP_THREAD.join(timeout=LOOP_SHUTDOWN_TIMEOUT)

        _close_loop(ASYNCIO_EVENT_LOOP)
        ASYNCIO_EVENT_LOOP = asyncio.new_event_loop()
        _LOOP_RUNNING.clear()

        def _thread_target(loop):
            log.info("Starting asyncio event loop")
            asyncio.set_event_loop(loop)
            loop.call_soon(_LOOP_RUNNING.set)
            try:
                loop.run_forever()
            finally:
                _LOOP_RUNNING.clear()

        ASYNCIO_LOOP_THREAD = threading.Thread(
            target=_thread_target,
            args=(ASYNCIO_EVENT_LOOP,),
            daemon=True,
            name="piper4nvda_asyncio",
        )
        ASYNCIO_LOOP_THREAD.start()
        if not _LOOP_RUNNING.wait(timeout=LOOP_STARTUP_TIMEOUT):
            log.error("Timed out waiting for the asyncio event loop to start")


def ensure_running():
    if _is_running():
        return
    with _LIFECYCLE_LOCK:
        if not _is_running():
            initialize()


def terminate():
    global THREADED_EXECUTOR, ASYNCIO_LOOP_THREAD, ASYNCIO_EVENT_LOOP
    global EXECUTOR_IS_SHUTDOWN

    with _LIFECYCLE_LOCK:
        log.info("Shutting down the thread pool executor")
        if THREADED_EXECUTOR is not None:
            THREADED_EXECUTOR.shutdown(wait=False)
            THREADED_EXECUTOR = None
        EXECUTOR_IS_SHUTDOWN = True
        if ASYNCIO_LOOP_THREAD is not None and ASYNCIO_LOOP_THREAD.is_alive():
            log.info("Shutting down asyncio event loop")
            loop_thread = ASYNCIO_LOOP_THREAD
            ASYNCIO_LOOP_THREAD = None
            if ASYNCIO_EVENT_LOOP is not None and ASYNCIO_EVENT_LOOP.is_running():
                ASYNCIO_EVENT_LOOP.call_soon_threadsafe(ASYNCIO_EVENT_LOOP.stop)
            loop_thread.join(timeout=LOOP_SHUTDOWN_TIMEOUT)
        _LOOP_RUNNING.clear()
        _close_loop(ASYNCIO_EVENT_LOOP)
        ASYNCIO_EVENT_LOOP = None


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
