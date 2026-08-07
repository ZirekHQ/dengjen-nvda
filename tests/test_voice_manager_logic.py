# coding: utf-8
"""
Tests for voice_manager_logic.py: the wx-free decisions behind the voice
manager UI, extracted from voice_manager.py so they can be driven on any
platform (see issue #65). The widgets themselves stay untestable here --
they subclass real wx types -- and are covered by tests_gui/ on Windows.
"""

import os

import pytest

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

import addonHandler
import dengjen_neural_voices.tts_system as tts_system

# In production this runs in the package __init__.py before anything using
# `_(...)` is imported. We load the module directly, so it happens here.
addonHandler.initTranslation()

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
    return DengjenVoice.from_path(os.path.join(os.sep, "voices", key))


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
        # Guards the #63 class of bug: the separator between language and
        # dialect is an underscore, the one between segments is a hyphen.
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
        assert not logic.is_active_voice(
            "espeak", "en_US-amy", "en_US-amy-medium"
        )

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
        # "de_DE" sorts before "en_US" by code, but "English" before "German"
        # by name -- the list the user reads is ordered by name.
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
