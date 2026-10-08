# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""Unit tests for structural_reading.py pure logic."""

import os

from tests.conftest import SYNTH_PKG_DIR, load_module_from_path

struct_reading = load_module_from_path(
    "dengjen_neural_voices.domain._structural_reading_under_test",
    os.path.join(SYNTH_PKG_DIR, "domain", "structural_reading.py"),
    package="dengjen_neural_voices.domain",
)
split_into_segments = struct_reading.split_into_segments
SpeechSegment = struct_reading.SpeechSegment


def test_empty_text():
    assert split_into_segments("") == []


def test_plain_text_without_asides():
    segments = split_into_segments(
        "Hello world, this is a test.", default_speaker="main", alt_speaker="alt"
    )
    assert len(segments) == 1
    assert segments[0].text == "Hello world, this is a test."
    assert segments[0].speaker_name == "main"


def test_parentheses_aside():
    text = "The quick brown fox (a clever animal) jumps over the dog."
    segments = split_into_segments(
        text, default_speaker="speaker1", alt_speaker="speaker2"
    )
    assert len(segments) == 3
    assert segments[0].text == "The quick brown fox "
    assert segments[0].speaker_name == "speaker1"
    assert segments[1].text == "(a clever animal)"
    assert segments[1].speaker_name == "speaker2"
    assert segments[2].text == " jumps over the dog."
    assert segments[2].speaker_name == "speaker1"


def test_square_brackets_aside():
    text = "Citation needed [12] for this claim."
    segments = split_into_segments(text, default_speaker="spk_a", alt_speaker="spk_b")
    assert len(segments) == 3
    assert segments[0].text == "Citation needed "
    assert segments[0].speaker_name == "spk_a"
    assert segments[1].text == "[12]"
    assert segments[1].speaker_name == "spk_b"
    assert segments[2].text == " for this claim."
    assert segments[2].speaker_name == "spk_a"


def test_quotes_aside():
    text = 'She said "Good morning!" to everyone.'
    segments = split_into_segments(
        text, default_speaker="narrator", alt_speaker="dialogue"
    )
    assert len(segments) == 3
    assert segments[0].text == "She said "
    assert segments[0].speaker_name == "narrator"
    assert segments[1].text == '"Good morning!"'
    assert segments[1].speaker_name == "dialogue"
    assert segments[2].text == " to everyone."
    assert segments[2].speaker_name == "narrator"


def test_japanese_brackets_aside():
    text = "彼が「こんにちは」と挨拶した。"
    segments = split_into_segments(
        text, default_speaker="narrator_ja", alt_speaker="voice_ja"
    )
    assert len(segments) == 3
    assert segments[0].text == "彼が"
    assert segments[0].speaker_name == "narrator_ja"
    assert segments[1].text == "「こんにちは」"
    assert segments[1].speaker_name == "voice_ja"
    assert segments[2].text == "と挨拶した。"
    assert segments[2].speaker_name == "narrator_ja"


def test_alt_speaker_falls_back_to_default_if_none():
    text = "Hello (aside) world"
    segments = split_into_segments(text, default_speaker="only_spk", alt_speaker=None)
    assert len(segments) == 3
    assert segments[1].speaker_name == "only_spk"
