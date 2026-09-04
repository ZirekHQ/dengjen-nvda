import pytest
from dengjen_neural_voices.ports.tts_backend import (
    BackendError,
    BackendUnavailableError,
    LoadedVoice,
    SynthesisError,
    SynthOptions,
    VoiceLoadError,
)


def test_synth_options_is_frozen():
    opts = SynthOptions(speaker="alice", length_scale=1.0, noise_scale=0.5, noise_w=0.8)
    assert opts.speaker == "alice"
    with pytest.raises(AttributeError):
        opts.speaker = "bob"


def test_loaded_voice_carries_defaults_as_synth_options():
    defaults = SynthOptions(
        speaker=None, length_scale=1.0, noise_scale=0.5, noise_w=0.8
    )
    voice = LoadedVoice(
        backend_voice_id="v1",
        supports_streaming_output=True,
        sample_rate=22050,
        speakers={"0": "Alice"},
        defaults=defaults,
    )
    assert voice.defaults is defaults
    assert voice.speakers == {"0": "Alice"}


@pytest.mark.parametrize(
    "exc_cls", [BackendUnavailableError, VoiceLoadError, SynthesisError]
)
def test_backend_errors_are_backend_error_subclasses(exc_cls):
    assert issubclass(exc_cls, BackendError)
    assert issubclass(BackendError, Exception)
