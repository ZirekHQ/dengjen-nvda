"""
Contract test for standard-voice synthesis latency and tail silence against
the real, vendored dengjen-tts-grpc.exe.

Tier 1 latency ceilings come from the worst-case (regressed) numbers
measured for the standard-voice synthesis path before it was last fixed;
staying under them means we haven't regressed back to that behavior. Tier 2
is Jakob Nielsen's general "user's flow of thought stays uninterrupted"
response-time limit (1s) -- an absolute ceiling independent of word count,
since there is no screen-reader-specific published latency standard to
anchor to.
"""

import os
import shutil
import struct
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

VOICE_KEY = "vi_VN-vivos-x_low"
VOICE_FILES_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vivos/x_low"
)
DOWNLOAD_TIMEOUT = 60
CALL_TIMEOUT = 30

# word count -> (text, tier-1 ceiling ms)
LATENCY_CASES = {
    1: ("chào", 112),
    3: ("xin chào bạn", 219),
    8: ("xin chào bạn tôi rất vui được gặp bạn", 235),
}
TIER2_CEILING_MS = 1000

SILENCE_SAMPLE_THRESHOLD = 500  # ~1.5% of int16 full scale
MAX_TAIL_SILENCE_MS = 50
SENTENCE_TEXT = "Một. Hai. Ba."


def _download(url, target_path):
    with (
        urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response,
        open(target_path, "wb") as f,
    ):
        f.write(response.read())


def _trailing_silence_ms(chunk: bytes, sample_rate: int) -> float:
    samples = struct.unpack(f"<{len(chunk) // 2}h", chunk[: len(chunk) // 2 * 2])
    silent = 0
    for sample in reversed(samples):
        if abs(sample) >= SILENCE_SAMPLE_THRESHOLD:
            break
        silent += 1
    return silent / sample_rate * 1000


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


@pytest.fixture(scope="session")
def loaded_voice(backend, downloaded_voice):
    return backend.load_voice(downloaded_voice)


class TestSynthesisLatencyContract:
    @pytest.mark.parametrize("word_count", sorted(LATENCY_CASES))
    def test_first_chunk_latency_stays_under_ceilings(
        self, backend, loaded_voice, word_count
    ):
        text, tier1_ceiling_ms = LATENCY_CASES[word_count]

        @aio.asyncio_coroutine_to_concurrent_future
        async def _time_to_first_chunk():
            start = time.perf_counter()
            async for _chunk in backend.synthesize(
                loaded_voice.backend_voice_id, text, None, None, None, None, False
            ):
                return time.perf_counter() - start
            raise AssertionError("expected at least one audio chunk")

        elapsed_ms = _time_to_first_chunk().result(timeout=CALL_TIMEOUT) * 1000

        assert elapsed_ms < TIER2_CEILING_MS, (
            f"{word_count}-word first-chunk latency {elapsed_ms:.1f}ms exceeds "
            f"the {TIER2_CEILING_MS}ms absolute ceiling"
        )
        assert elapsed_ms < tier1_ceiling_ms, (
            f"{word_count}-word first-chunk latency {elapsed_ms:.1f}ms exceeds "
            f"the {tier1_ceiling_ms}ms regression ceiling"
        )

    def test_no_unrequested_tail_silence_between_chunks(self, backend, loaded_voice):
        @aio.asyncio_coroutine_to_concurrent_future
        async def _collect():
            chunks = []
            async for chunk in backend.synthesize(
                loaded_voice.backend_voice_id,
                SENTENCE_TEXT,
                None,
                None,
                None,
                0,
                False,
            ):
                chunks.append(chunk)
            return chunks

        chunks = _collect().result(timeout=CALL_TIMEOUT)
        assert chunks, "expected at least one audio chunk"

        for index, chunk in enumerate(chunks):
            tail_ms = _trailing_silence_ms(chunk, loaded_voice.sample_rate)
            assert tail_ms < MAX_TAIL_SILENCE_MS, (
                f"chunk {index} has {tail_ms:.1f}ms of trailing silence despite "
                f"sentence_silence_ms=0 (max allowed {MAX_TAIL_SILENCE_MS}ms)"
            )
