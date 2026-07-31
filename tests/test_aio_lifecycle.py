import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "addon"
    / "synthDrivers"
    / "sonata_neural_voices"
    / "aio.py"
)


@pytest.fixture
def real_aio_module():
    module_name = "sonata_neural_voices._aio_lifecycle_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sonata_neural_voices"
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        module.terminate()
        if not module.ASYNCIO_EVENT_LOOP.is_closed():
            module.ASYNCIO_EVENT_LOOP.close()
        sys.modules.pop(module_name, None)


def test_initialize_is_idempotent(real_aio_module):
    aio = real_aio_module
    aio.initialize()
    first_thread = aio.ASYNCIO_LOOP_THREAD
    first_executor = aio.THREADED_EXECUTOR

    aio.initialize()

    assert aio.ASYNCIO_LOOP_THREAD is first_thread
    assert aio.THREADED_EXECUTOR is first_executor
    assert first_thread.is_alive()
    assert aio.ASYNCIO_EVENT_LOOP.is_running()


def test_terminate_is_idempotent_and_runtime_can_restart(real_aio_module):
    aio = real_aio_module
    aio.initialize()
    first_thread = aio.ASYNCIO_LOOP_THREAD

    aio.terminate()
    aio.terminate()

    assert aio.ASYNCIO_LOOP_THREAD is None
    assert aio.THREADED_EXECUTOR is None
    assert not first_thread.is_alive()

    aio.initialize()

    assert aio.ASYNCIO_LOOP_THREAD is not first_thread
    assert aio.ASYNCIO_LOOP_THREAD.is_alive()

    @aio.asyncio_coroutine_to_concurrent_future
    async def probe():
        return "restarted"

    assert probe().result(timeout=5) == "restarted"


def test_decorated_coroutine_self_starts_runtime(real_aio_module):
    aio = real_aio_module

    @aio.asyncio_coroutine_to_concurrent_future
    async def probe():
        return 42

    assert probe().result(timeout=5) == 42
    assert aio.ASYNCIO_LOOP_THREAD.is_alive()
