"""Regenerates the vendored gRPC stubs from the proto in the pinned dengjen-tts release.

grpcio-tools 1.62.3 (protobuf 4.25 gencode; vendored runtime is 4.24.4) ships wheels
only up to Python 3.12, so run this from a Python 3.12 (or older) venv.
Run it from the repository root (paths are relative to the repo root).

Usage:
    uv venv --python 3.12 /tmp/proto-venv
    uv pip install --python /tmp/proto-venv --only-binary=:all: grpcio-tools==1.62.3
    /tmp/proto-venv/bin/python update_grpc_protos.py    # proto version comes from dengjen-tts.lock
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

from update_dengjen_tts import REPO, _get, read_lock

PROTO_DIR = Path(
    "addon/synthDrivers/dengjen_neural_voices/adapters/dengjen_grpc/grpc_protos"
)
PROTO_NAME = "dengjen_grpc.proto"
PROTO_PATH_IN_REPO = "crates/frontends/grpc/proto/dengjen_grpc.proto"
GENCODE_MARKER = "Protobuf Python Version: 4.25"
ABSOLUTE_IMPORT = re.compile(r"^import (\w+_pb2) as (\w+)$", re.MULTILINE)


def proto_url(version):
    return f"https://raw.githubusercontent.com/{REPO}/v{version}/{PROTO_PATH_IN_REPO}"


def relativize_imports(source):
    return ABSOLUTE_IMPORT.sub(r"from . import \1 as \2", source)


def _run_protoc(proto_file):
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{PROTO_DIR}",
            f"--python_out={PROTO_DIR}",
            f"--pyi_out={PROTO_DIR}",
            f"--grpc_python_out={PROTO_DIR}",
            str(proto_file),
        ],
        check=True,
    )


def _require_grpc_tools():
    if importlib.util.find_spec("grpc_tools") is None:
        raise SystemExit(
            "grpc_tools is not installed; run from a Python 3.12 or older venv "
            "with grpcio-tools==1.62.3 installed."
        )


def main():
    _require_grpc_tools()
    version, _ = read_lock()
    proto_file = PROTO_DIR / PROTO_NAME
    proto_file.write_bytes(_get(proto_url(version)))
    _run_protoc(proto_file)
    if GENCODE_MARKER not in (PROTO_DIR / "dengjen_grpc_pb2.py").read_text():
        raise SystemExit(
            f"Generated code is not '{GENCODE_MARKER}'; "
            "install grpcio-tools==1.62.3 in a Python 3.12 or older venv."
        )
    grpc_file = PROTO_DIR / "dengjen_grpc_pb2_grpc.py"
    grpc_file.write_text(relativize_imports(grpc_file.read_text()))
    print(f"Regenerated gRPC stubs from dengjen-tts v{version}.")


if __name__ == "__main__":
    main()
