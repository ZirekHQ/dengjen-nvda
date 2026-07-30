# coding: utf-8

# Copyright (c) 2026 Adam Rastrand
# This file is covered by the GNU General Public License.

import os
from pathlib import Path


DEFAULT_EXECUTION_PROVIDER = "auto"
DEFAULT_GPU_MIN_PHONEMES = 300
DEFAULT_DIRECTML_DEVICE_ID = 0
ONNXRUNTIME_DLL = "onnxruntime.dll"


def build_engine_environment(bin_directory, base_environment=None):
    """Build the child-process environment for the Sonata inference engine.

    The bundled ONNX Runtime is always selected explicitly so an unrelated
    system installation cannot change the engine ABI. Users and automated
    tests may override the provider, threshold, and DirectML adapter through
    environment variables.
    """
    bin_directory = Path(bin_directory).resolve()
    env = dict(os.environ if base_environment is None else base_environment)
    env["ORT_DYLIB_PATH"] = os.fspath(bin_directory / ONNXRUNTIME_DLL)
    env.setdefault("SONATA_EXECUTION_PROVIDER", DEFAULT_EXECUTION_PROVIDER)
    env.setdefault("SONATA_GPU_MIN_PHONEMES", str(DEFAULT_GPU_MIN_PHONEMES))
    env.setdefault("SONATA_DIRECTML_DEVICE_ID", str(DEFAULT_DIRECTML_DEVICE_ID))

    path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    bin_path = os.fspath(bin_directory)
    if not any(os.path.normcase(entry) == os.path.normcase(bin_path) for entry in path_entries):
        path_entries.insert(0, bin_path)
    env["PATH"] = os.pathsep.join(path_entries)
    return env
