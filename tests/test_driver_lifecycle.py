import builtins
import importlib.util
import sys
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "addon"
    / "synthDrivers"
    / "sonata_neural_voices"
    / "__init__.py"
)


def ready_future(value=None):
    future = Future()
    future.set_result(value)
    return future


@pytest.fixture
def driver_module(monkeypatch):
    monkeypatch.setattr(builtins, "_", lambda value: value, raising=False)
    module_name = "sonata_neural_voices._driver_lifecycle_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "sonata_neural_voices"
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(module_name, None)


def test_failed_initialization_can_be_terminated_safely(driver_module):
    failure = Future()
    failure.set_exception(RuntimeError("engine failed"))
    driver_module._GRPC_IS_INIT = failure
    driver = driver_module.SynthDriver.__new__(driver_module.SynthDriver)

    with pytest.raises(RuntimeError, match="initialize Sonata services"):
        driver_module.SynthDriver.__init__(driver)

    assert driver_module.aio.terminate.call_count == 1
    driver.terminate()
    driver.terminate()
    assert driver.tts is None
    assert driver._players == {}
    assert driver_module.aio.terminate.call_count == 3


def test_driver_can_start_stop_and_start_again(driver_module):
    voice = SimpleNamespace(
        key="en_US-test-medium",
        standard_variant_key="en_US-test-medium",
        fast_variant_key="en_US-test+RT-medium",
        variant="standard",
        sample_rate=22050,
        language="en_US",
        name="Test voice",
        properties={"quality": "medium"},
    )

    class FakeSpeechOptions:
        def __init__(self, voice):
            self.voice = voice

    class FakeTextToSpeechSystem:
        shutdown_calls = 0

        @classmethod
        def load_piper_voices_from_nvda_config_dir(cls):
            return [voice]

        @staticmethod
        def get_voice_variants(voice_key):
            return (voice_key, voice_key.replace("-medium", "+RT-medium"))

        def __init__(self, voices, speech_options):
            self.voices = voices
            self.speech_options = speech_options

        def shutdown(self):
            type(self).shutdown_calls += 1

    driver_module.SpeechOptions = FakeSpeechOptions
    driver_module.SonataTextToSpeechSystem = FakeTextToSpeechSystem
    driver_module._GRPC_IS_INIT = ready_future(None)
    driver_module.grpc_client.check_grpc_server.return_value = ready_future("test")
    driver_module.grpc_client.initialize.return_value = ready_future(None)
    driver_module.config.conf["speech"]["sonata_neural_voices"]["voice"] = voice.key
    driver_module.aio.initialize.reset_mock()
    driver_module.aio.terminate.reset_mock()
    driver_module.grpc_client.initialize.reset_mock()

    first = driver_module.SynthDriver()
    first.terminate()
    second = driver_module.SynthDriver()
    second.terminate()

    assert driver_module.aio.initialize.call_count == 2
    assert driver_module.aio.terminate.call_count == 2
    assert driver_module.grpc_client.initialize.call_count == 2
    assert FakeTextToSpeechSystem.shutdown_calls == 2
