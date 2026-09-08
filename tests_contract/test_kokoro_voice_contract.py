"""
Contract test proving the real, vendored dengjen-tts-grpc.exe loads a
Kokoro voice config and synthesizes through it end-to-end.

Downloads only 2 of the 54 presets (not all 54) to keep CI light -- the
engine's config schema doesn't care how many are listed. _build_kokoro_config
below duplicates kokoro_download.build_kokoro_config's exact shape rather
than importing it -- see the module-level note in the plan/PR for why.

Gives a coarse smoke-level timing bound, not a tuned regression ceiling
(unlike test_synthesis_latency_contract.py's Piper numbers) -- issue #31's
precise real-hardware latency question still needs a manual Windows run.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import types
import urllib.request

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

KOKORO_REPO_RESOLVE_URL = (
    "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
)
PRESETS_UNDER_TEST = ["af_heart", "am_adam"]
DOWNLOAD_TIMEOUT = 60
CALL_TIMEOUT = 30
SMOKE_CEILING_MS = 2000  # coarse -- see module docstring


def _build_kokoro_config(preset_names):
    """Duplicates kokoro_download.build_kokoro_config's exact shape -- see
    the module docstring for why this isn't imported instead."""
    return {
        "model_type": "kokoro",
        "model_path": "model.onnx",
        "voices_dir": "voices",
        "vocab_path": "tokenizer.json",
        "sample_rate": 24000,
        "voices": list(preset_names),
    }


def _download(relative_path, target_path):
    url = f"{KOKORO_REPO_RESOLVE_URL}/{relative_path}"
    with (
        urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response,
        open(target_path, "wb") as f,
    ):
        f.write(response.read())


@pytest.fixture(scope="session")
def kokoro_config_path(tmp_path_factory):
    install_dir = tmp_path_factory.mktemp("kokoro")
    (install_dir / "voices").mkdir()
    _download("onnx/model.onnx", install_dir / "model.onnx")
    _download("tokenizer.json", install_dir / "tokenizer.json")
    for name in PRESETS_UNDER_TEST:
        _download(f"voices/{name}.bin", install_dir / "voices" / f"{name}.bin")
    config_path = install_dir / "config.json"
    config_path.write_text(
        json.dumps(_build_kokoro_config(PRESETS_UNDER_TEST)), encoding="utf-8"
    )
    return str(config_path)


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

    def test_synthesizes_non_empty_audio_within_smoke_ceiling(
        self, backend, loaded_voice
    ):
        @aio.asyncio_coroutine_to_concurrent_future
        async def _time_to_first_chunk():
            start = time.perf_counter()
            async for chunk in backend.synthesize(
                loaded_voice.backend_voice_id,
                "Hello, this is a test.",
                None,
                None,
                None,
                None,
                loaded_voice.supports_streaming_output,
            ):
                assert chunk, "expected a non-empty audio chunk"
                return time.perf_counter() - start
            raise AssertionError("expected at least one audio chunk")

        elapsed = _time_to_first_chunk().result(timeout=CALL_TIMEOUT)
        assert (elapsed * 1000) < SMOKE_CEILING_MS, (
            f"first-chunk latency {elapsed * 1000:.1f}ms exceeds the "
            f"{SMOKE_CEILING_MS}ms smoke ceiling -- this is not issue #31's "
            "precise latency number, just a build-didn't-regress-wildly check"
        )
