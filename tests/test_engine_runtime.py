import os
from pathlib import Path

from sonata_neural_voices.engine_runtime import (
    DEFAULT_DIRECTML_DEVICE_ID,
    DEFAULT_EXECUTION_PROVIDER,
    DEFAULT_GPU_MIN_PHONEMES,
    build_engine_environment,
)


def test_build_engine_environment_sets_safe_defaults(tmp_path):
    env = build_engine_environment(tmp_path, {"PATH": r"C:\Windows\System32"})

    assert DEFAULT_GPU_MIN_PHONEMES == 0
    assert env["ORT_DYLIB_PATH"] == os.fspath(
        Path(tmp_path).resolve() / "onnxruntime.dll"
    )
    assert env["SONATA_EXECUTION_PROVIDER"] == DEFAULT_EXECUTION_PROVIDER
    assert env["SONATA_GPU_MIN_PHONEMES"] == str(DEFAULT_GPU_MIN_PHONEMES)
    assert env["SONATA_DIRECTML_DEVICE_ID"] == str(DEFAULT_DIRECTML_DEVICE_ID)
    assert env["PATH"].split(os.pathsep)[0] == os.fspath(Path(tmp_path).resolve())


def test_build_engine_environment_preserves_performance_overrides(tmp_path):
    base = {
        "PATH": os.fspath(Path(tmp_path).resolve()),
        "SONATA_EXECUTION_PROVIDER": "cpu",
        "SONATA_STREAMING_EXECUTION_PROVIDER": "cpu",
        "SONATA_GPU_MIN_PHONEMES": "999",
        "SONATA_DIRECTML_DEVICE_ID": "2",
    }

    env = build_engine_environment(tmp_path, base)

    assert env["SONATA_EXECUTION_PROVIDER"] == "cpu"
    assert env["SONATA_STREAMING_EXECUTION_PROVIDER"] == "cpu"
    assert env["SONATA_GPU_MIN_PHONEMES"] == "999"
    assert env["SONATA_DIRECTML_DEVICE_ID"] == "2"
    assert env["PATH"] == base["PATH"]
