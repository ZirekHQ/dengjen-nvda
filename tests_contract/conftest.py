"""
conftest.py for the gRPC contract tests — these talk to the real, vendored
dengjen-tts-grpc.exe over a real gRPC channel.

Deliberately not part of tests/: that suite's conftest.py stubs `grpc`
itself (sys.modules["grpc"] = MagicMock()) for every test in it, and
pytest.ini's testpaths=tests keeps this directory out of a bare `pytest`
run, so the two never collide in the same process. Run this tree with
`pytest tests_contract/` explicitly.

No NVDA stubbing here. The generated protobuf/grpc client
(synthDrivers/dengjen_neural_voices/grpc_client/grpc_protos/) has no NVDA
dependencies, so tests talk to it directly instead of going through
grpc_client/__init__.py — that module pulls in globalVars, logHandler, and
Windows subprocess flags meant for NVDA's own background process lifecycle,
not a short-lived test process.

Windows-only: dengjen-tts-grpc.exe is a Windows PE binary and the vendored
`grpc` package under lib/ is compiled for cp313-win_amd64. Test modules
must check `sys.platform` and call `pytest.skip(..., allow_module_level=True)`
before importing `grpc` — a plain skipif marker does not prevent pytest
from importing the module (and therefore `grpc`) during collection.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

import pytest

_TESTS_CONTRACT_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(_TESTS_CONTRACT_DIR, ".."))
_SYNTH_PKG_DIR = os.path.join(
    REPO_ROOT, "addon", "synthDrivers", "dengjen_neural_voices"
)

LIB_DIRECTORY = os.path.join(_SYNTH_PKG_DIR, "lib")
BIN_DIRECTORY = os.path.join(_SYNTH_PKG_DIR, "bin")
GRPC_CLIENT_DIR = os.path.join(_SYNTH_PKG_DIR, "adapters", "dengjen_grpc")
GRPC_SERVER_EXE = os.path.join(BIN_DIRECTORY, "dengjen-tts-grpc.exe")


for _p in (LIB_DIRECTORY, GRPC_CLIENT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


KOKORO_REPO_RESOLVE_URL = (
    "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
)
KOKORO_PRESETS = ["af_heart", "am_adam"]
KOKORO_DOWNLOAD_TIMEOUT = 60


def build_kokoro_config(preset_names):
    """Mirror of kokoro_download.build_kokoro_config; keep in sync."""
    return {
        "model_type": "kokoro",
        "model_path": "model.onnx",
        "voices_dir": "voices",
        "vocab_path": "tokenizer.json",
        "sample_rate": 24000,
        "voices": list(preset_names),
    }


def _download_kokoro_file(relative_path, target_path):
    url = f"{KOKORO_REPO_RESOLVE_URL}/{relative_path}"
    with (
        urllib.request.urlopen(url, timeout=KOKORO_DOWNLOAD_TIMEOUT) as response,
        open(target_path, "wb") as f,
    ):
        f.write(response.read())


def _download_kokoro(install_dir):
    (install_dir / "voices").mkdir(parents=True, exist_ok=True)
    _download_kokoro_file("onnx/model.onnx", install_dir / "model.onnx")
    _download_kokoro_file("tokenizer.json", install_dir / "tokenizer.json")
    for name in KOKORO_PRESETS:
        _download_kokoro_file(
            f"voices/{name}.bin", install_dir / "voices" / f"{name}.bin"
        )
    config = json.dumps(build_kokoro_config(KOKORO_PRESETS))
    (install_dir / "config.json").write_text(config, encoding="utf-8")


@pytest.fixture(scope="session")
def kokoro_config_path(tmp_path_factory):
    """Kokoro install shared by the Kokoro contract tests; reused from
    DENGJEN_KOKORO_CACHE when set. config.json is written last, so its
    presence marks a complete install."""
    cache_dir = os.environ.get("DENGJEN_KOKORO_CACHE")
    install_dir = Path(cache_dir) if cache_dir else tmp_path_factory.mktemp("kokoro")
    if not (install_dir / "config.json").exists():
        _download_kokoro(install_dir)
    return str(install_dir / "config.json")
