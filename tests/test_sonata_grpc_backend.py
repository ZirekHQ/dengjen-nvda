# coding: utf-8
"""
Tests for SonataGrpcBackend's TTSBackend surface: that it correctly
translates the underlying module-level gRPC calls' failures into the
TTSBackend port's typed errors. The gRPC calls themselves (against a real
sonata-grpc.exe) are covered by tests_contract/, not here.
"""

from concurrent.futures import Future

import pytest

import dengjen_neural_voices.adapters.sonata_grpc as sonata_grpc
from dengjen_neural_voices.ports.tts_backend import (
    BackendUnavailableError,
    SynthesisError,
    VoiceLoadError,
)

backend = sonata_grpc.SonataGrpcBackend()


def _failed_future(exc):
    f = Future()
    f.set_exception(exc)
    return f


def test_initialize_wraps_a_failure_as_backend_unavailable(monkeypatch):
    monkeypatch.setattr(sonata_grpc, "initialize", lambda: _failed_future(RuntimeError("no port")))
    with pytest.raises(BackendUnavailableError):
        backend.initialize()


def test_check_version_wraps_a_failure_as_backend_unavailable(monkeypatch):
    monkeypatch.setattr(sonata_grpc, "check_grpc_server", lambda: _failed_future(TimeoutError()))
    with pytest.raises(BackendUnavailableError):
        backend.check_version()


def test_load_voice_wraps_a_failure_as_voice_load_error(monkeypatch):
    monkeypatch.setattr(sonata_grpc, "load_voice", lambda path: _failed_future(RuntimeError("bad proto")))
    with pytest.raises(VoiceLoadError):
        backend.load_voice("/tmp/v/config.json")


def test_load_voice_maps_the_response_fields(monkeypatch):
    class _FakeInfo:
        voice_id = "v1"
        supports_streaming_output = True
        class audio:
            sample_rate = 22050
        speakers = {"0": "Alice"}
        class synth_options:
            speaker = "Alice"
            length_scale = 1.0
            noise_scale = 0.5
            noise_w = 0.8

    ready = Future()
    ready.set_result(_FakeInfo())
    monkeypatch.setattr(sonata_grpc, "load_voice", lambda path: ready)

    loaded = backend.load_voice("/tmp/v/config.json")

    assert loaded.backend_voice_id == "v1"
    assert loaded.sample_rate == 22050
    assert loaded.speakers == {"0": "Alice"}
    assert loaded.defaults.noise_scale == 0.5


def test_set_synth_options_wraps_a_failure_as_voice_load_error(monkeypatch):
    monkeypatch.setattr(
        sonata_grpc, "set_synth_options", lambda voice_id, **kw: _failed_future(RuntimeError("boom"))
    )
    with pytest.raises(VoiceLoadError):
        backend.set_synth_options("v1", noise_scale=0.5)


def test_synthesize_wraps_a_failure_as_synthesis_error():
    import asyncio

    async def _boom(**kwargs):
        raise RuntimeError("stream broke")
        yield b""  # pragma: no cover -- makes this an async generator

    async def _run():
        with pytest.raises(SynthesisError):
            async for _ in backend.synthesize("v1", "hi", None, None, None, None, False):
                pass

    import dengjen_neural_voices.adapters.sonata_grpc as mod
    orig = mod.speak
    mod.speak = _boom
    try:
        asyncio.run(_run())
    finally:
        mod.speak = orig


def test_synthesize_yields_wav_samples_bytes_not_the_raw_message():
    """Regression test: synthesize() briefly re-yielded the raw protobuf
    message instead of unwrapping .wav_samples (caught and fixed during this
    branch's own work). speak() yields message-shaped objects, not bytes, so
    a fixture asserting bytes-in/bytes-out here would pass even if
    synthesize() forgot to extract .wav_samples."""
    import asyncio
    import types

    async def _fake_speak(**kwargs):
        yield types.SimpleNamespace(wav_samples=b"abc")
        yield types.SimpleNamespace(wav_samples=b"def")

    async def _run():
        return [
            chunk
            async for chunk in backend.synthesize("v1", "hi", None, None, None, None, False)
        ]

    import dengjen_neural_voices.adapters.sonata_grpc as mod
    orig = mod.speak
    mod.speak = _fake_speak
    try:
        chunks = asyncio.run(_run())
    finally:
        mod.speak = orig

    assert chunks == [b"abc", b"def"]
