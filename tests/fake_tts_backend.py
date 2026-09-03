# coding: utf-8
"""Shared TTSBackend test double.

A plain class, not a MagicMock() spec -- consistent with this project's
convention of stubbing interfaces as plain classes (see CLAUDE.md's testing
guardrails). Records every call so tests can assert on call shape, and lets
a test configure a specific exception to be raised from any method.
"""

from dataclasses import replace

from dengjen_neural_voices.ports.tts_backend import LoadedVoice, SynthOptions


class FakeTTSBackend:
    def __init__(self, *, version="1.0.0-fake", default_loaded_voice=None, synthesize_chunks=(b"",)):
        self.version = version
        self.default_loaded_voice = default_loaded_voice or LoadedVoice(
            backend_voice_id="fake-remote-id",
            supports_streaming_output=False,
            sample_rate=22050,
            speakers={},
            defaults=SynthOptions(speaker=None, length_scale=1.0, noise_scale=0.667, noise_w=0.8),
        )
        self.synthesize_chunks = list(synthesize_chunks)
        self.voices_by_config_path = {}
        self._synth_options_by_voice_id = {}

        self.initialize_calls = 0
        self.check_version_calls = 0
        self.shutdown_calls = 0
        self.load_voice_calls = []
        self.get_synth_options_calls = []
        self.set_synth_options_calls = []
        self.synthesize_calls = []

        self._raise_on_initialize = None
        self._raise_on_load_voice = None
        self._raise_on_synthesize = None

    # -- test configuration --------------------------------------------

    def raise_on_initialize(self, exc):
        self._raise_on_initialize = exc

    def raise_on_load_voice(self, exc):
        self._raise_on_load_voice = exc

    def raise_on_synthesize(self, exc):
        self._raise_on_synthesize = exc

    # -- TTSBackend surface --------------------------------------------

    def initialize(self):
        self.initialize_calls += 1
        if self._raise_on_initialize is not None:
            raise self._raise_on_initialize

    def check_version(self):
        self.check_version_calls += 1
        return self.version

    def shutdown(self):
        self.shutdown_calls += 1

    def load_voice(self, config_path):
        self.load_voice_calls.append(config_path)
        if self._raise_on_load_voice is not None:
            raise self._raise_on_load_voice
        loaded = self.voices_by_config_path.get(config_path, self.default_loaded_voice)
        self._synth_options_by_voice_id.setdefault(loaded.backend_voice_id, loaded.defaults)
        return loaded

    def get_synth_options(self, backend_voice_id):
        self.get_synth_options_calls.append(backend_voice_id)
        return self._synth_options_by_voice_id[backend_voice_id]

    def set_synth_options(self, backend_voice_id, **kwargs):
        self.set_synth_options_calls.append((backend_voice_id, kwargs))
        current = self._synth_options_by_voice_id[backend_voice_id]
        updates = {k: v for k, v in kwargs.items() if v is not None}
        self._synth_options_by_voice_id[backend_voice_id] = replace(current, **updates)

    async def synthesize(self, backend_voice_id, text, rate, volume, pitch, sentence_silence_ms, streaming):
        self.synthesize_calls.append((backend_voice_id, text))
        if self._raise_on_synthesize is not None:
            raise self._raise_on_synthesize
        for chunk in self.synthesize_chunks:
            yield chunk
