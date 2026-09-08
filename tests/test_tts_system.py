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

    def test_parses_standard_key_sets_piper_model_type(self, backend):
        v = DengjenVoice.from_path("/tmp/en-john-medium", backend)
        assert v.model_type == "piper"

    def test_from_path_reads_sidecar_for_non_piper_directory_name(
        self, backend, tmp_path
    ):
        voice_dir = tmp_path / "kokoro-multilingual"
        voice_dir.mkdir()
        (voice_dir / "voice.json").write_text(
            '{"model_type": "kokoro", "name": "Kokoro Multilingual", '
            '"language": "en", "description": "54 presets"}',
            encoding="utf-8",
        )

        v = DengjenVoice.from_path(voice_dir, backend)

        assert v.model_type == "kokoro"
        assert v.name == "Kokoro Multilingual"
        assert v.language == "en"


class TestDengjenVoiceLoadIgnoresTheSidecar:
    def test_picks_the_engine_config_even_when_the_sidecar_sorts_first(
        self, backend, tmp_path
    ):
        voice_dir = tmp_path / "en-john-medium"
        voice_dir.mkdir()
        # Write the sidecar FIRST, matching the real install order (both
        # PiperVoiceDownloader._install and install_voice_from_tar_archive
        # write voice.json before the payload) -- this is also the FAT/
        # exFAT filesystem-ordering failure mode this test guards against.
        (voice_dir / "voice.json").write_text(
            '{"model_type": "piper", "name": "john", "language": "en"}',
            encoding="utf-8",
        )
        (voice_dir / "en-john-medium.onnx.json").write_text(
            '{"some": "engine config"}', encoding="utf-8"
        )

        v = DengjenVoice.from_path(voice_dir, backend)
        v.load()

        assert v.config_path.name == "en-john-medium.onnx.json"


class TestDengjenVoiceFastVariantGating:
    def test_piper_voice_reports_is_fast_from_key(self, backend):
        v = DengjenVoice.from_path("/tmp/en-john+RT-medium", backend)
        assert v.is_fast is True

    def test_non_piper_voice_is_never_fast(self, backend, tmp_path):
        voice_dir = tmp_path / "kokoro-multilingual"
        voice_dir.mkdir()
        (voice_dir / "voice.json").write_text(
            '{"model_type": "kokoro", "name": "Kokoro", "language": "en"}',
            encoding="utf-8",
        )
        v = DengjenVoice.from_path(voice_dir, backend)
        assert v.is_fast is False


class TestDengjenVoiceProsodyControlGating:
    def test_piper_voice_reads_noise_scale_from_backend(self, backend):
        v = _make_voice(backend)
        assert v.noise_scale == pytest.approx(0.667)

    def test_kokoro_voice_noise_scale_is_a_harmless_no_op(self, backend, tmp_path):
        voice_dir = tmp_path / "kokoro-multilingual"
        voice_dir.mkdir()
        (voice_dir / "voice.json").write_text(
            '{"model_type": "kokoro", "name": "Kokoro", "language": "en"}',
            encoding="utf-8",
        )
        v = DengjenVoice.from_path(voice_dir, backend)
        v.remote_id = "fake-remote-id"

        assert v.noise_scale is None
        assert backend.get_synth_options_calls == []

        v.noise_scale = 0.9  # must not raise, must not reach the backend

        assert backend.set_synth_options_calls == []


class TestSpeakerBypassesTheProsodyControlGate:
    def test_speaker_reaches_the_backend_for_a_non_prosody_model_type(self, backend):
        v = _make_voice(
            backend,
            key="kokoro-multilingual",
            name="Kokoro",
            is_multi_speaker=True,
            speakers={"0": "af_heart", "1": "am_adam"},
        )
        v.model_type = "kokoro"

        assert v.speaker == "default"
        assert backend.get_synth_options_calls == [v.remote_id]

        v.speaker = "af_heart"

        assert backend.set_synth_options_calls == [
            (v.remote_id, {"speaker": "af_heart"})
        ]
        # noise_scale must still be gated off for this model_type
        assert v.noise_scale is None


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


class TestGetVoiceVariantsOnNonPiperKeys:
    def test_returns_the_key_unchanged_for_a_non_three_part_key(self):
        result = DengjenTextToSpeechSystem.get_voice_variants("kokoro-multilingual")
        assert result == ("kokoro-multilingual", "kokoro-multilingual")


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


class TestLoadAllVoicesFromNvdaConfigDir:
    def test_merges_piper_and_kokoro_directories(self, backend, tmp_path, monkeypatch):
        piper_dir = tmp_path / "piper"
        kokoro_dir = tmp_path / "kokoro"
        piper_dir.mkdir()
        kokoro_dir.mkdir()
        (piper_dir / "en-john-medium").mkdir()
        (kokoro_dir / "kokoro-multilingual").mkdir()
        (kokoro_dir / "kokoro-multilingual" / "voice.json").write_text(
            '{"model_type": "kokoro", "name": "Kokoro", "language": "en"}',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "dengjen_neural_voices.domain.tts_system.DENGJEN_VOICES_DIR",
            str(piper_dir),
        )
        monkeypatch.setattr(
            "dengjen_neural_voices.domain.tts_system.DENGJEN_KOKORO_VOICES_DIR",
            str(kokoro_dir),
        )
        monkeypatch.setattr(
            "dengjen_neural_voices.domain.tts_system.migrate_voices_directory",
            lambda: None,
        )

        voices = DengjenTextToSpeechSystem.load_all_voices_from_nvda_config_dir(backend)

        assert sorted(v.key for v in voices) == [
            "en-john-medium",
            "kokoro-multilingual",
        ]
