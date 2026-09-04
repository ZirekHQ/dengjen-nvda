import asyncio

import pytest
from dengjen_neural_voices.ports.tts_backend import BackendUnavailableError

from tests.fake_tts_backend import FakeTTSBackend


def test_load_voice_returns_the_default_loaded_voice_and_records_the_call():
    backend = FakeTTSBackend()
    loaded = backend.load_voice("/tmp/en-test-medium/config.json")
    assert loaded.backend_voice_id == "fake-remote-id"
    assert backend.load_voice_calls == ["/tmp/en-test-medium/config.json"]


def test_set_synth_options_updates_get_synth_options():
    backend = FakeTTSBackend()
    loaded = backend.load_voice("/tmp/v/config.json")
    backend.set_synth_options(loaded.backend_voice_id, noise_scale=1.5)
    assert backend.get_synth_options(loaded.backend_voice_id).noise_scale == 1.5
    # Explicit None values must not clobber existing fields.
    backend.set_synth_options(
        loaded.backend_voice_id, length_scale=2.0, noise_scale=None
    )
    assert backend.get_synth_options(loaded.backend_voice_id).noise_scale == 1.5
    assert backend.get_synth_options(loaded.backend_voice_id).length_scale == 2.0


def test_raise_on_initialize_is_honored():
    backend = FakeTTSBackend()
    backend.raise_on_initialize(BackendUnavailableError("no vcruntime"))
    with pytest.raises(BackendUnavailableError):
        backend.initialize()
    assert backend.initialize_calls == 1


def test_synthesize_records_the_call_and_yields_configured_chunks():
    async def _collect():
        backend = FakeTTSBackend(synthesize_chunks=[b"abc", b"def"])
        loaded = backend.load_voice("/tmp/v/config.json")
        chunks = [
            chunk
            async for chunk in backend.synthesize(
                loaded.backend_voice_id, "hello", None, None, None, None, False
            )
        ]
        assert chunks == [b"abc", b"def"]
        assert backend.synthesize_calls == [(loaded.backend_voice_id, "hello")]

    asyncio.run(_collect())
