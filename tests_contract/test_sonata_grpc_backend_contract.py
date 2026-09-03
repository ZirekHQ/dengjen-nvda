# coding: utf-8
"""
Contract test for SonataGrpcBackend against the real, vendored
sonata-grpc.exe. Unlike test_grpc_contract.py (which talks to the raw
protobuf stub directly, bypassing any Python wrapper by design), this
exercises the actual TTSBackend adapter production code will call --
catching "the wrapper doesn't behave like the port says" before it reaches
SynthDriver.
"""

import os
import sys
import tempfile
import types
import urllib.request

import pytest

if sys.platform != "win32":
    pytest.skip("sonata-grpc.exe is a Windows binary", allow_module_level=True)

# Ensures the real, vendored grpc/NVDA-adjacent modules this backend imports
# are importable outside NVDA. tests_contract/ deliberately does not use
# tests/nvda_stubs.py (see conftest.py's own docstring): that module stubs
# `grpc` itself as a MagicMock, which would shadow the real vendored grpc
# these tests must exercise. Provide the minimal real stand-ins instead.
#
# adapters/sonata_grpc/__init__.py's own import chain (const.py, helpers.py,
# aio.py) needs globalVars, logHandler, wx and gui.settingsDialogs -- not
# domain/tts_system.py's or SynthDriver's much larger NVDA surface, because
# dengjen_neural_voices/__init__.py is never allowed to run for real below.
sys.modules.setdefault(
    "globalVars",
    types.SimpleNamespace(appArgs=types.SimpleNamespace(configPath=tempfile.mkdtemp()), appDir=os.getcwd()),
)
sys.modules.setdefault("logHandler", types.SimpleNamespace(log=types.SimpleNamespace(
    info=lambda *a, **k: None, error=lambda *a, **k: None,
    debug=lambda *a, **k: None, exception=lambda *a, **k: None,
)))
sys.modules.setdefault("wx", types.SimpleNamespace(GetTopLevelWindows=lambda: []))
sys.modules.setdefault("gui", types.SimpleNamespace(messageBox=lambda *a, **k: None, mainFrame=None))
sys.modules.setdefault(
    "gui.settingsDialogs",
    types.SimpleNamespace(NVDASettingsDialog=type("NVDASettingsDialog", (), {}),
                           SpeechSettingsPanel=type("SpeechSettingsPanel", (), {})),
)

from tests_contract.conftest import REPO_ROOT

# dengjen_neural_voices/__init__.py imports SynthDriver (synthDriverHandler,
# speech, config, ui, ...) at module load time -- a much larger NVDA surface
# than this test needs. Pre-registering the package in sys.modules with its
# real __path__ makes plain relative imports inside adapters/sonata_grpc
# (`from ...const import ...`, `from ...helpers import ...`) resolve
# correctly while skipping that __init__.py entirely.
_SYNTH_PKG_DIR = os.path.join(REPO_ROOT, "addon", "synthDrivers", "dengjen_neural_voices")
_dengjen_pkg = types.ModuleType("dengjen_neural_voices")
_dengjen_pkg.__path__ = [_SYNTH_PKG_DIR]
sys.modules.setdefault("dengjen_neural_voices", _dengjen_pkg)

from dengjen_neural_voices.adapters.sonata_grpc import SonataGrpcBackend

VOICE_KEY = "vi_VN-vivos-x_low"
VOICE_FILES_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vivos/x_low"
)
DOWNLOAD_TIMEOUT = 60


def _download(url, target_path):
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, open(target_path, "wb") as f:
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
    b = SonataGrpcBackend()
    b.initialize()
    yield b
    b.shutdown()


class TestSonataGrpcBackendContract:
    def test_check_version_returns_a_non_empty_string(self, backend):
        version = backend.check_version()
        assert isinstance(version, str)
        assert version.strip() != ""

    def test_load_voice_and_synthesize_returns_non_empty_audio(self, backend, downloaded_voice):
        loaded = backend.load_voice(downloaded_voice)
        assert loaded.backend_voice_id
        assert loaded.sample_rate > 0

        import asyncio

        async def _collect():
            chunks = []
            async for chunk in backend.synthesize(
                loaded.backend_voice_id, "xin chào", None, None, None, None, False
            ):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(_collect())
        assert chunks, "expected at least one audio chunk from synthesize()"
        assert sum(len(c) for c in chunks) > 0
