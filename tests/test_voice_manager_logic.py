"""
Tests for voice_manager_logic.py: the wx-free decisions behind the voice
manager UI, extracted from voice_manager.py so they can be driven on any
platform (see issue #65). The widgets themselves stay untestable here --
they subclass real wx types -- and are covered by tests_gui/ on Windows.
"""

import os

import addonHandler
from dengjen_neural_voices.domain import tts_system

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path
from tests.fake_tts_backend import FakeTTSBackend



addonHandler.initTranslation()




_backend = FakeTTSBackend()

logic = load_module_from_path(
    "dengjen_tts_global_plugin._voice_manager_logic_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "voice_manager_logic.py"),
    package="dengjen_tts_global_plugin",
)

voice_download = load_module_from_path(
    "dengjen_tts_global_plugin._voice_download_for_logic_tests",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "voice_download.py"),
    package="dengjen_tts_global_plugin",
)

DengjenVoice = tts_system.DengjenVoice


def _installed(key):
    """A real DengjenVoice, as load_piper_voices_from_nvda_config_dir yields."""
    return DengjenVoice.from_path(os.path.join(os.sep, "voices", key), _backend)


def _language(code, name_english, country_english="Country"):
    return voice_download.PiperVoiceLanguage(
        code=code,
        family=code.split("_")[0],
        region=code.split("_")[-1],
        name_native=name_english,
        name_english=name_english,
        country_english=country_english,
    )


def _online(key, name, language, **kwargs):
    return voice_download.PiperVoice(
        key=key,
        name=name,
        quality=voice_download.PiperVoiceQualityLevel.Medium,
        num_speakers=kwargs.pop("num_speakers", 1),
        speaker_id_map=kwargs.pop("speaker_id_map", {}),
        language=language,
        files=[],
        has_rt_variant=kwargs.pop("has_rt_variant", False),
        standard_variant_installed=kwargs.pop("standard_variant_installed", False),
        fast_variant_installed=kwargs.pop("fast_variant_installed", False),
    )


class TestInstalledVoiceDisplayName:
    def test_standard_voice_is_labelled_standard(self):
        voice = _installed("en_US-amy-medium")
        assert logic.installed_voice_display_name(voice) == "amy (standard)"

    def test_rt_voice_is_labelled_fast(self):
        voice = _installed("en_US-amy+RT-medium")
        assert logic.installed_voice_display_name(voice) == "amy (fast)"


class TestSanitizeModelCard:
    def test_strips_markdown_heading_and_emphasis_markers(self):
        assert logic.sanitize_model_card("# Title\n**bold**") == " Title\nbold"

    def test_leaves_plain_text_untouched(self):
        assert logic.sanitize_model_card("plain text") == "plain text"


class TestVoiceIdFromKey:
    def test_drops_the_quality_segment(self):
        assert logic.voice_id_from_key("en_US-amy-medium") == "en_US-amy"

    def test_keeps_the_rt_marker(self):
        assert logic.voice_id_from_key("en_US-amy+RT-medium") == "en_US-amy+RT"

    def test_underscored_language_survives(self):
        
        
        assert logic.voice_id_from_key("pt_BR-faber-medium") == "pt_BR-faber"


class TestIsActiveVoice:
    def test_true_when_synth_and_voice_both_match(self):
        assert logic.is_active_voice(
            "dengjen_neural_voices", "en_US-amy", "en_US-amy-medium"
        )

    def test_false_for_a_different_voice_on_the_same_synth(self):
        assert not logic.is_active_voice(
            "dengjen_neural_voices", "en_US-amy", "en_US-ryan-medium"
        )

    def test_false_when_another_synth_is_active(self):
        assert not logic.is_active_voice("espeak", "en_US-amy", "en_US-amy-medium")

    def test_quality_does_not_affect_the_match(self):
        assert logic.is_active_voice(
            "dengjen_neural_voices", "en_US-amy", "en_US-amy-high"
        )


class TestGroupVoicesByLanguage:
    def test_groups_voices_under_their_language(self):
        en = _language("en_US", "English")
        de = _language("de_DE", "German")
        voices = [
            _online("en_US-amy-medium", "amy", en),
            _online("de_DE-thorsten-medium", "thorsten", de),
            _online("en_US-ryan-medium", "ryan", en),
        ]
        languages, lang_to_voices = logic.group_voices_by_language(voices)
        assert set(languages) == {en, de}
        assert len(lang_to_voices[en]) == 2
        assert len(lang_to_voices[de]) == 1

    def test_voices_within_a_language_are_sorted_by_key(self):
        en = _language("en_US", "English")
        voices = [
            _online("en_US-ryan-medium", "ryan", en),
            _online("en_US-amy-medium", "amy", en),
        ]
        _languages, lang_to_voices = logic.group_voices_by_language(voices)
        assert [v.key for v in lang_to_voices[en]] == [
            "en_US-amy-medium",
            "en_US-ryan-medium",
        ]

    def test_languages_are_sorted_by_english_name_not_by_code(self):
        
        
        en = _language("en_US", "English")
        de = _language("de_DE", "German")
        voices = [
            _online("de_DE-thorsten-medium", "thorsten", de),
            _online("en_US-amy-medium", "amy", en),
        ]
        languages, _lang_to_voices = logic.group_voices_by_language(voices)
        assert [lang.name_english for lang in languages] == ["English", "German"]

    def test_empty_input_yields_empty_output(self):
        languages, lang_to_voices = logic.group_voices_by_language([])
        assert languages == []
        assert lang_to_voices == {}


class TestInstalledListState:
    def test_buttons_disabled_when_no_voices_installed(self):
        state = logic.installed_list_state([], "dengjen_neural_voices")
        assert state.buttons_enabled is False

    def test_buttons_enabled_when_a_voice_is_installed(self):
        state = logic.installed_list_state(
            [_installed("en_US-amy-medium")], "dengjen_neural_voices"
        )
        assert state.buttons_enabled is True

    def test_remove_needs_at_least_two_voices(self):
        one = logic.installed_list_state(
            [_installed("en_US-amy-medium")], "dengjen_neural_voices"
        )
        two = logic.installed_list_state(
            [_installed("en_US-amy-medium"), _installed("en_US-ryan-medium")],
            "dengjen_neural_voices",
        )
        assert one.remove_enabled is False
        assert two.remove_enabled is True

    def test_dengjen_synth_matched_case_insensitively_by_substring(self):
        
        
        assert logic.installed_list_state([], "Dengjen_Neural_Voices").is_dengjen_synth
        assert logic.installed_list_state([], "dengjen").is_dengjen_synth

    def test_other_synths_are_not_dengjen(self):
        assert not logic.installed_list_state([], "espeak").is_dengjen_synth

    def test_remove_enabled_is_independent_of_the_active_synth(self):
        
        
        state = logic.installed_list_state(
            [_installed("en_US-amy-medium"), _installed("en_US-ryan-medium")],
            "espeak",
        )
        assert state.remove_enabled is True
        assert state.is_dengjen_synth is False


class TestDownloadButtonState:
    def test_standard_download_offered_when_not_installed(self):
        voice = _online("en_US-amy-medium", "amy", _language("en_US", "English"))
        assert logic.download_button_state(voice).std_enabled is True

    def test_standard_download_withheld_when_already_installed(self):
        voice = _online(
            "en_US-amy-medium",
            "amy",
            _language("en_US", "English"),
            standard_variant_installed=True,
        )
        assert logic.download_button_state(voice).std_enabled is False

    def test_fast_download_withheld_when_voice_has_no_rt_variant(self):
        voice = _online(
            "en_US-amy-medium",
            "amy",
            _language("en_US", "English"),
            has_rt_variant=False,
        )
        assert logic.download_button_state(voice).rt_enabled is False

    def test_fast_download_offered_when_rt_exists_and_is_not_installed(self):
        voice = _online(
            "en_US-amy-medium",
            "amy",
            _language("en_US", "English"),
            has_rt_variant=True,
        )
        assert logic.download_button_state(voice).rt_enabled is True

    def test_fast_download_withheld_when_rt_already_installed(self):
        voice = _online(
            "en_US-amy-medium",
            "amy",
            _language("en_US", "English"),
            has_rt_variant=True,
            fast_variant_installed=True,
        )
        assert logic.download_button_state(voice).rt_enabled is False

    def test_single_speaker_voice_offers_no_speaker_choice(self):
        voice = _online(
            "en_US-amy-medium",
            "amy",
            _language("en_US", "English"),
            num_speakers=1,
            speaker_id_map={"amy": 0},
        )
        state = logic.download_button_state(voice)
        assert state.speaker_enabled is False
        assert state.speakers == ()

    def test_multi_speaker_voice_lists_its_speakers_in_map_order(self):
        voice = _online(
            "en_US-libritts-medium",
            "libritts",
            _language("en_US", "English"),
            num_speakers=3,
            speaker_id_map={"p3": 0, "p1": 1, "p2": 2},
        )
        state = logic.download_button_state(voice)
        assert state.speaker_enabled is True
        assert state.speakers == ("p3", "p1", "p2")
