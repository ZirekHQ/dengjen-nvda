# coding: utf-8
"""
Contract test against the real, vendored sonata-grpc.exe: starts the actual
engine binary and confirms it answers the GetSonataVersion handshake over a
real gRPC channel — the same call grpc_client.check_grpc_server() makes
during NVDA startup.

Also exercises LoadVoice + SynthesizeUtterance against a real trained
voice model, downloaded from HuggingFace at test time (see
TestVoiceSynthesis below) — the first test to touch actual speech
synthesis rather than the mocked grpc_client used everywhere in tests/.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

if sys.platform != "win32":
    # A plain skipif marker would not be enough: pytest still imports this
    # module during collection, and `import grpc` below fails outright on
    # any platform other than the one the vendored lib/grpc was built for.
    pytest.skip("sonata-grpc.exe is a Windows binary", allow_module_level=True)

import grpc

import grpc_protos.sonata_grpc_pb2 as msgs
import grpc_protos.sonata_grpc_pb2_grpc as pb2_grpc

from tests_contract.conftest import BIN_DIRECTORY, GRPC_SERVER_EXE

STARTUP_TIMEOUT = 15
STARTUP_POLL_INTERVAL = 0.5


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def grpc_server():
    assert os.path.exists(GRPC_SERVER_EXE), f"sonata-grpc.exe not found at {GRPC_SERVER_EXE}"

    port = _find_free_port()
    log_path = os.path.join(tempfile.mkdtemp(), "sonata-grpc.log")
    env = os.environ.copy()
    env.update({
        "SONATA_GRPC_SERVER_PORT": str(port),
        # Only needed for voice loading/synthesis, which this handshake-only
        # test never exercises; an empty directory is enough for the server
        # to start.
        "SONATA_ESPEAKNG_DATA_DIRECTORY": tempfile.mkdtemp(),
        "SONATA_GRPC": "info",
    })

    with open(log_path, "wb") as log_file:
        process = subprocess.Popen(
            args=GRPC_SERVER_EXE,
            cwd=BIN_DIRECTORY,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    channel = grpc.insecure_channel(f"localhost:{port}")
    stub = pb2_grpc.sonata_grpcStub(channel)

    deadline = time.monotonic() + STARTUP_TIMEOUT
    last_error = None
    ready = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            stub.GetSonataVersion(msgs.Empty(), timeout=STARTUP_POLL_INTERVAL)
            ready = True
            break
        except grpc.RpcError as exc:
            last_error = exc
            time.sleep(STARTUP_POLL_INTERVAL)

    if not ready:
        channel.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        with open(log_path, "rb") as log_file:
            server_log = log_file.read().decode(errors="replace")
        pytest.fail(
            f"sonata-grpc.exe did not become ready within {STARTUP_TIMEOUT}s "
            f"(exit code: {process.poll()}, last gRPC error: {last_error}).\n"
            f"Server log:\n{server_log}"
        )

    yield stub

    channel.close()
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


class TestVersionHandshake:
    def test_get_sonata_version_returns_a_non_empty_version_string(self, grpc_server):
        response = grpc_server.GetSonataVersion(msgs.Empty())
        assert isinstance(response.version, str)
        assert response.version.strip() != ""


# vi_VN-vivos-x_low is deliberately the cheapest real Piper voice to test
# against: x_low is the lowest quality tier and vivos is one of the smaller
# datasets (~28MB total). Actual synthesis quality isn't the point here —
# only that LoadVoice/SynthesizeUtterance work end-to-end against the real
# engine, which the mocked grpc_client everywhere else in tests/ can't prove.
VOICE_KEY = "vi_VN-vivos-x_low"
VOICE_FILES_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN/vivos/x_low"
)
DOWNLOAD_TIMEOUT = 60
CALL_TIMEOUT = 30


def _download(url, target_path):
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, open(target_path, "wb") as f:
        f.write(response.read())


@pytest.fixture(scope="session")
def downloaded_voice(tmp_path_factory):
    """Download the voice once per session; returns the config (.onnx.json) path.

    LoadVoice takes the config path and expects the matching .onnx file
    alongside it (same naming convention SonataVoice.load() relies on in
    production).
    """
    voice_dir = tmp_path_factory.mktemp("voice")
    onnx_path = voice_dir / f"{VOICE_KEY}.onnx"
    config_path = voice_dir / f"{VOICE_KEY}.onnx.json"
    _download(f"{VOICE_FILES_BASE_URL}/{VOICE_KEY}.onnx", onnx_path)
    _download(f"{VOICE_FILES_BASE_URL}/{VOICE_KEY}.onnx.json", config_path)
    return str(config_path)


class TestVoiceSynthesis:
    def test_load_voice_and_synthesize_returns_non_empty_audio(self, grpc_server, downloaded_voice):
        voice_info = grpc_server.LoadVoice(msgs.VoicePath(config_path=downloaded_voice), timeout=CALL_TIMEOUT)
        assert voice_info.voice_id
        assert voice_info.audio.sample_rate > 0

        utterance = msgs.Utterance(voice_id=voice_info.voice_id, text="xin chào")
        frames = list(grpc_server.SynthesizeUtterance(utterance, timeout=CALL_TIMEOUT))

        assert frames, "expected at least one audio frame from SynthesizeUtterance"
        assert sum(len(frame.wav_samples) for frame in frames) > 0
