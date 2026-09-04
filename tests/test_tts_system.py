"""
Tests for the core TTS system logic in domain/tts_system.py.

All NVDA internals are stubbed by conftest.py. No gRPC/NVDA dependency: every
voice here is constructed against a FakeTTSBackend.
"""

from pathlib import Path

import pytest
from dengjen_neural_voices.const import (
    DEFAULT_PITCH,
    DEFAULT_RATE,
    DEFAULT_VOLUME,
    FALLBACK_SPEAKER_NAME,
    IGNORED_PUNCS,
)
from dengjen_neural_voices.domain.tts_system import (
    DengjenTextToSpeechSystem,
    DengjenVoice,
    Scales,
    SilenceProvider,
    SpeechOptions,
    VoiceNotFoundError,
)
from dengjen_neural_voices.ports.tts_backend import SynthOptions

from tests.fake_tts_backend import FakeTTSBackend


def _make_voice(
    backend,
    key="en-test-medium",
    name="Test",
    language="en",
    sample_rate=22050,
    is_multi_speaker=False,
    speakers=None,
):
    """Create a fully loaded DengjenVoice against the given fake backend."""
    v = DengjenVoice(
        key=key,
        name=name,
        language=language,
        description="A test voice",
        location=Path("/tmp/fake-voice"),
        backend=backend,
        properties={"quality": "medium"},
    )
    v.remote_id = "fake-remote-id"
    v.supports_streaming_output = False
    v.sample_rate = sample_rate
    v.default_scales = Scales(length_scale=1.0, noise_scale=0.667, noise_w=0.8)
    v.is_multi_speaker = is_multi_speaker
    v.speakers = speakers or {}
    v.speaker_names = list((speakers or {}).values())
    v.default_speaker = None
    backend._synth_options_by_voice_id.setdefault(
        v.remote_id,
        SynthOptions(
            speaker="default", length_scale=1.0, noise_scale=0.667, noise_w=0.8
        ),
    )
    return v


@pytest.fixture
def backend():
    return FakeTTSBackend()


@pytest.fixture
def single_voice(backend):
    return _make_voice(backend)


@pytest.fixture
def multi_voice(backend):
    return _make_voice(
        backend,
        key="en-multi-medium",
        name="Multi",
        is_multi_speaker=True,
        speakers={"0": "Alice", "1": "Bob"},
    )


@pytest.fixture
def voice_list(backend, single_voice):
    return [
        single_voice,
        _make_voice(
            backend,
            key="en-test+RT-medium",
            name="Test",
            language="en",
            sample_rate=16000,
        ),
        _make_voice(backend, key="fr-durand-medium", name="Durand", language="fr"),
    ]


@pytest.fixture
def tts(voice_list):
    opts = SpeechOptions.__new__(SpeechOptions)
    opts.voice = voice_list[0]
    opts.rate = None
    opts.volume = None
    opts.pitch = None
    opts.sentence_silence_ms = None
    system = DengjenTextToSpeechSystem.__new__(DengjenTextToSpeechSystem)
    system.voices = voice_list
    system.speech_options = opts
    return system


class TestDengjenVoiceFromPath:
    def test_parses_standard_key(self, backend):
        v = DengjenVoice.from_path("/tmp/en-john-medium", backend)
        assert v.key == "en-john-medium"
        assert v.name == "john"
        assert v.language == "en"
        assert v.properties["quality"] == "medium"

    def test_parses_rt_key(self, backend):
        v = DengjenVoice.from_path("/tmp/en-john+RT-medium", backend)
        assert v.name == "john"

    def test_invalid_path_raises(self, backend):
        with pytest.raises(ValueError):
            DengjenVoice.from_path("/tmp/notavalidkey", backend)

    def test_is_fast_property(self, single_voice, backend):
        assert not single_voice.is_fast
        fast = _make_voice(backend, key="en-test+RT-medium")
        assert fast.is_fast

    def test_variant_property(self, single_voice, backend):
        assert single_voice.variant == "standard"
        fast = _make_voice(backend, key="en-test+RT-medium")
        assert fast.variant == "fast"

    def test_standard_variant_key(self, single_voice):
        assert single_voice.standard_variant_key == "en-test-medium"

    def test_fast_variant_key(self, single_voice):
        assert single_voice.fast_variant_key == "en-test+RT-medium"


class TestSilenceProvider:
    def test_generates_correct_byte_length(self):
        provider = SilenceProvider(time_ms=100, sample_rate=22050)
        audio = provider.generate_audio()
        expected_samples = int((100 / 1000.0) * 22050)
        assert len(audio) == expected_samples * 2

    def test_generates_silence_bytes(self):
        provider = SilenceProvider(time_ms=50, sample_rate=16000)
        audio = provider.generate_audio()
        assert all(b == 0 for b in audio)

    def test_zero_duration_returns_empty_bytes(self):
        provider = SilenceProvider(time_ms=0, sample_rate=22050)
        assert provider.generate_audio() == b""


class TestTTSDefaults:
    def test_rate_default(self, tts):
        assert tts.rate == DEFAULT_RATE

    def test_volume_default(self, tts):
        assert tts.volume == DEFAULT_VOLUME

    def test_pitch_default(self, tts):
        assert tts.pitch == DEFAULT_PITCH

    def test_voice_key_matches(self, tts, voice_list):
        assert tts.voice == voice_list[0].key

    def test_language_matches_voice(self, tts):
        assert tts.language == "en"


class TestTTSVoiceSwitching:
    def test_set_valid_voice(self, tts, voice_list):
        tts.voice = voice_list[1].key
        assert tts.voice == voice_list[1].key

    def test_set_invalid_voice_raises(self, tts):
        with pytest.raises(VoiceNotFoundError):
            tts.voice = "xx-nonexistent-low"

    def test_set_language_exact_match(self, tts, voice_list):
        tts.language = "fr"
        assert tts.voice == voice_list[2].key

    def test_set_language_no_match_raises(self, tts):
        with pytest.raises(VoiceNotFoundError):
            tts.language = "ja"

    def test_set_language_returns_to_en_voice(self, tts, voice_list):
        """Setting language to 'fr' then back to 'en' should restore an English voice."""
        tts.language = "fr"
        assert tts.language == "fr"
        tts.language = "en"
        assert tts.language == "en"

    def test_set_bare_language_matches_dialect_voice(self, backend):
        """A bare language code (e.g. 'en' from a LangChangeCommand) must match an
        installed dialect voice (e.g. 'en_US') rather than raising VoiceNotFoundError.

        Regression test for issue #63: the prefix match compared against a
        hyphen-joined code ('en-') while voice.language is underscore-joined
        ('en_US'), so the match always failed for dialect voices.
        """
        dialect_voice = _make_voice(
            backend, key="en_US-alex-medium", name="Alex", language="en_US"
        )
        opts = SpeechOptions.__new__(SpeechOptions)
        opts.voice = dialect_voice
        opts.rate = opts.volume = opts.pitch = opts.sentence_silence_ms = None
        system = DengjenTextToSpeechSystem.__new__(DengjenTextToSpeechSystem)
        system.voices = [dialect_voice]
        system.speech_options = opts

        system.language = "en"

        assert system.voice == dialect_voice.key

    @pytest.mark.parametrize("requested", ["en-US", "en_US", "EN-us", "en_us"])
    def test_set_language_normalizes_dash_and_case(self, backend, requested):
        """normalizeLanguage converts dashes to underscores and fixes casing
        before the driver ever compares languages, so a dash- or
        differently-cased request must resolve to the same dialect voice as
        the canonical 'en_US' form."""
        dialect_voice = _make_voice(
            backend, key="en_US-alex-medium", name="Alex", language="en_US"
        )
        opts = SpeechOptions.__new__(SpeechOptions)
        opts.voice = dialect_voice
        opts.rate = opts.volume = opts.pitch = opts.sentence_silence_ms = None
        system = DengjenTextToSpeechSystem.__new__(DengjenTextToSpeechSystem)
        system.voices = [dialect_voice]
        system.speech_options = opts

        system.language = requested

        assert system.voice == dialect_voice.key
        assert system.language == "en_US"


class TestTTSParameters:
    def test_set_rate(self, tts):
        tts.rate = 75
        assert tts.rate == 75

    def test_set_volume(self, tts):
        tts.volume = 80
        assert tts.volume == 80

    def test_set_pitch(self, tts):
        tts.pitch = 60
        assert tts.pitch == 60


class TestSynthesisContext:
    def test_context_restores_rate(self, tts):
        tts.rate = 30
        with tts.create_synthesis_context():
            tts.rate = 99
        assert tts.rate == 30

    def test_context_restores_volume(self, tts):
        tts.volume = 50
        with tts.create_synthesis_context():
            tts.volume = 10
        assert tts.volume == 50

    def test_context_restores_voice(self, tts, voice_list):
        original = tts.voice
        with tts.create_synthesis_context():
            tts.voice = voice_list[1].key
        assert tts.voice == original


class TestProviders:
    def test_create_speech_provider_stores_text(self, tts):
        provider = tts.create_speech_provider("Hello world")
        assert provider.text == "Hello world"

    def test_create_break_provider_stores_time(self, tts):
        provider = tts.create_break_provider(500)
        assert provider.time_ms == 500
        assert provider.sample_rate == tts.speech_options.voice.sample_rate


class TestGetVoiceVariants:
    def test_standard_and_rt_keys(self):
        std, rt = DengjenTextToSpeechSystem.get_voice_variants("en-john-medium")
        assert std == "en-john-medium"
        assert rt == "en-john+RT-medium"

    def test_rt_key_is_normalized(self):
        std, rt = DengjenTextToSpeechSystem.get_voice_variants("en-john+RT-medium")
        assert std == "en-john-medium"
        assert rt == "en-john+RT-medium"


class TestSpeakerSingleVoice:
    def test_speaker_returns_fallback_for_single_speaker(self, tts):
        assert tts.speaker == FALLBACK_SPEAKER_NAME

    def test_set_speaker_on_non_multispeaker_is_noop(self, tts):

        tts.speaker = FALLBACK_SPEAKER_NAME


class TestSynthOptionAccessors:
    @pytest.mark.parametrize(
        "name, expected",
        [("noise_scale", 0.667), ("length_scale", 1.0), ("noise_w", 0.8)],
    )
    def test_getter_reads_option_from_backend(self, multi_voice, name, expected):
        assert getattr(multi_voice, name) == expected

    @pytest.mark.parametrize("name", ["noise_scale", "length_scale", "noise_w"])
    def test_setter_forwards_option_to_backend(self, multi_voice, backend, name):
        backend.set_synth_options_calls.clear()
        setattr(multi_voice, name, 1.5)
        assert backend.set_synth_options_calls == [(multi_voice.remote_id, {name: 1.5})]

    def test_speaker_getter_reads_from_backend_for_multi_speaker(self, multi_voice):
        assert multi_voice.speaker == "default"

    def test_speaker_setter_forwards_to_backend_for_multi_speaker(
        self, multi_voice, backend
    ):
        backend.set_synth_options_calls.clear()
        multi_voice.speaker = "Bob"
        assert backend.set_synth_options_calls == [
            (multi_voice.remote_id, {"speaker": "Bob"})
        ]

    def test_accessor_propagates_a_backend_error(self, multi_voice, backend):
        from dengjen_neural_voices.ports.tts_backend import VoiceLoadError

        def _boom(voice_id):
            raise VoiceLoadError("timed out")

        backend.get_synth_options = _boom
        with pytest.raises(VoiceLoadError):
            _ = multi_voice.noise_scale


class TestConstants:
    def test_ignored_puncs_is_frozenset(self):
        assert isinstance(IGNORED_PUNCS, frozenset)

    def test_default_values_are_in_range(self):
        assert 0 <= DEFAULT_RATE <= 100
        assert 0 <= DEFAULT_VOLUME <= 100
        assert 0 <= DEFAULT_PITCH <= 100

    def test_fallback_speaker_name_is_string(self):
        assert isinstance(FALLBACK_SPEAKER_NAME, str)
        assert FALLBACK_SPEAKER_NAME
