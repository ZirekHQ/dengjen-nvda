"""
Contract test for DengjenGrpcBackend against the real, vendored
dengjen-tts-grpc.exe. Unlike test_grpc_contract.py (which talks to the raw
protobuf stub directly, bypassing any Python wrapper by design), this
exercises the actual TTSBackend adapter production code will call --
catching "the wrapper doesn't behave like the port says" before it reaches
SynthDriver.
"""

import os
import shutil
import sys
import tempfile
import types
import urllib.request

import pytest

if sys.platform != "win32":
    pytest.skip("dengjen-tts-grpc.exe is a Windows binary", allow_module_level=True)

import espeakng_loader

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

VOICE_KEY = "vi_VN-vivos-x_low"
VOICE_FILES_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vivos/x_low"
)
DOWNLOAD_TIMEOUT = 60
CALL_TIMEOUT = 30


def _download(url, target_path):
    with (
        urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response,
        open(target_path, "wb") as f,
    ):
        f.write(response.read())


@pytest.fixture(scope="session")
def downloaded_voice(tmp_path_factory):
    voice_dir = tmp_path_factory.mktemp("voice")
    onnx_path = voice_dir / f"{VOICE_KEY}.onnx"
    config_path = voice_dir / f"{VOICE_KEY}.onnx.json"
    _download(f"{VOICE_FILES_BASE_URL}/{VOICE_KEY}.onnx", onnx_path)
    _download(f"{VOICE_FILES_BASE_URL}/{VOICE_KEY}.onnx.json", config_path)
    return str(config_path)


@pytest.fixture(scope="session")
def backend():
    b = DengjenGrpcBackend()
    b.initialize()
    yield b
    b.shutdown()


class TestDengjenGrpcBackendContract:
    def test_check_version_returns_a_non_empty_string(self, backend):
        version = backend.check_version()
        assert isinstance(version, str)
        assert version.strip() != ""

    def test_load_voice_and_synthesize_returns_non_empty_audio(
        self, backend, downloaded_voice
    ):
        loaded = backend.load_voice(downloaded_voice)
        assert loaded.backend_voice_id
        assert loaded.sample_rate > 0

        @aio.asyncio_coroutine_to_concurrent_future
        async def _collect():
            chunks = []
            async for chunk in backend.synthesize(
                loaded.backend_voice_id, "xin chào", None, None, None, None, False
            ):
                chunks.append(chunk)
            return chunks

        chunks = _collect().result(timeout=CALL_TIMEOUT)
        assert chunks, "expected at least one audio chunk from synthesize()"
        assert sum(len(c) for c in chunks) > 0

    def test_sentence_silence_ms_appends_audio_samples(self, backend, downloaded_voice):
        """Verify non-zero sentence_silence_ms appends PCM silence to synthesized audio."""
        loaded = backend.load_voice(downloaded_voice)
        pause_ms = 300
        backend.set_synth_options(loaded.backend_voice_id, noise_scale=0.0, noise_w=0.0)

        def _total_bytes(silence_ms):
            @aio.asyncio_coroutine_to_concurrent_future
            async def _collect():
                total = 0
                async for chunk in backend.synthesize(
                    loaded.backend_voice_id,
                    "Một. Hai.",
                    None,
                    None,
                    None,
                    silence_ms,
                    False,
                ):
                    total += len(chunk)
                return total

            return _collect().result(timeout=CALL_TIMEOUT)

        try:
            bytes_without_pause = _total_bytes(0)
            bytes_with_pause = _total_bytes(pause_ms)
        finally:
            backend.set_synth_options(
                loaded.backend_voice_id,
                noise_scale=loaded.defaults.noise_scale,
                noise_w=loaded.defaults.noise_w,
            )

        expected_min_extra_bytes = int(loaded.sample_rate * (pause_ms / 1000.0)) * 2
        assert bytes_with_pause - bytes_without_pause >= expected_min_extra_bytes
