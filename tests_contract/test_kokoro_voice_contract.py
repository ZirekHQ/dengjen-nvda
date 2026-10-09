"""
Contract test proving the real, vendored dengjen-tts-grpc.exe loads a
Kokoro voice config and synthesizes non-empty audio through it end-to-end.

Uses 2 of the 54 presets (KOKORO_PRESETS in conftest.py) to keep CI light --
the engine's config schema doesn't care how many are listed. First-chunk
latency is gated by test_synthesis_latency_contract.py.
"""

import os
import shutil
import sys
import tempfile
import types

import espeakng_loader
import pytest

if sys.platform != "win32":
    pytest.skip("dengjen-tts-grpc.exe is a Windows binary", allow_module_level=True)


_APP_DIR = tempfile.mkdtemp()
_SYNTH_DRIVERS_DIR = os.path.join(_APP_DIR, "synthDrivers")
shutil.copytree(
    espeakng_loader.get_data_path(), os.path.join(_SYNTH_DRIVERS_DIR, "espeak-ng-data")
)

sys.modules.setdefault(
    "globalVars",
    types.SimpleNamespace(
        appArgs=types.SimpleNamespace(configPath=tempfile.mkdtemp()), appDir=_APP_DIR
    ),
)
sys.modules.setdefault(
    "logHandler",
    types.SimpleNamespace(
        log=types.SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )
    ),
)
sys.modules.setdefault("wx", types.SimpleNamespace(GetTopLevelWindows=list))
sys.modules.setdefault(
    "gui", types.SimpleNamespace(messageBox=lambda *a, **k: None, mainFrame=None)
)
sys.modules.setdefault(
    "gui.settingsDialogs",
    types.SimpleNamespace(
        NVDASettingsDialog=type("NVDASettingsDialog", (), {}),
        SpeechSettingsPanel=type("SpeechSettingsPanel", (), {}),
    ),
)

from tests_contract.conftest import REPO_ROOT

_SYNTH_PKG_DIR = os.path.join(
    REPO_ROOT, "addon", "synthDrivers", "dengjen_neural_voices"
)
_dengjen_pkg = types.ModuleType("dengjen_neural_voices")
_dengjen_pkg.__path__ = [_SYNTH_PKG_DIR]
sys.modules.setdefault("dengjen_neural_voices", _dengjen_pkg)

from dengjen_neural_voices import aio
from dengjen_neural_voices.adapters.dengjen_grpc import DengjenGrpcBackend

from tests_contract.conftest import KOKORO_PRESETS as PRESETS_UNDER_TEST

CALL_TIMEOUT = 30


@pytest.fixture(scope="session")
def backend():
    b = DengjenGrpcBackend()
    b.initialize()
    yield b
    b.shutdown()


@pytest.fixture(scope="session")
def loaded_voice(backend, kokoro_config_path):
    voice = backend.load_voice(kokoro_config_path)

    @aio.asyncio_coroutine_to_concurrent_future
    async def _warm_up():
        async for _chunk in backend.synthesize(
            voice.backend_voice_id,
            "Hello.",
            None,
            None,
            None,
            None,
            voice.supports_streaming_output,
        ):
            pass

    _warm_up().result(timeout=CALL_TIMEOUT)
    return voice


class TestKokoroVoiceContract:
    def test_reports_both_requested_presets_as_speakers(self, loaded_voice):
        assert set(loaded_voice.speakers.values()) == set(PRESETS_UNDER_TEST)
        assert 0 in loaded_voice.speakers

    def test_synthesizes_non_empty_audio(self, backend, loaded_voice):
        @aio.asyncio_coroutine_to_concurrent_future
        async def _first_chunk():
            async for chunk in backend.synthesize(
                loaded_voice.backend_voice_id,
                "Hello, this is a test.",
                None,
                None,
                None,
                None,
                loaded_voice.supports_streaming_output,
            ):
                return chunk
            raise AssertionError("expected at least one audio chunk")

        assert _first_chunk().result(timeout=CALL_TIMEOUT), (
            "expected a non-empty audio chunk"
        )
