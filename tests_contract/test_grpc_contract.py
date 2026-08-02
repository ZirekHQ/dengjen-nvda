# coding: utf-8
"""
Contract test against the real, vendored sonata-grpc.exe: starts the actual
engine binary and confirms it answers the GetSonataVersion handshake over a
real gRPC channel — the same call grpc_client.check_grpc_server() makes
during NVDA startup.

Deliberately narrow (see issue #65): this only proves the process starts
and speaks the expected protocol. It does not exercise LoadVoice/
SynthesizeUtterance, since that needs a real trained voice model and none
are vendored in this repo — a real HuggingFace download in CI is a bigger,
flakier step planned as a separate follow-up once this handshake-level
test is proven out.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

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
