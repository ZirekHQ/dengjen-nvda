# coding: utf-8

# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

"""wx-free decisions behind the voice manager UI.

Imports nothing from wx, gui, winsound, miniaudio or synthDriverHandler, so
this module is importable and testable on any platform. voice_manager.py
keeps the widgets and the side effects; the branches it takes live here.
"""

from __future__ import annotations

import dataclasses
import operator
import typing

DENGJEN_SYNTH_NAME = "dengjen_neural_voices"


def installed_voice_display_name(voice) -> str:
    return f"{voice.name} ({voice.variant})"


def sanitize_model_card(content: str) -> str:
    return content.replace("#", "").replace("*", "")


def voice_id_from_key(voice_key: str) -> str:
    return "-".join(voice_key.split("-")[:-1])


def is_active_voice(synth_name: str, synth_voice: str, voice_key: str) -> bool:
    return synth_name == DENGJEN_SYNTH_NAME and synth_voice == voice_id_from_key(
        voice_key
    )


def group_voices_by_language(voices) -> typing.Tuple[list, dict]:
    lang_to_voices: dict = {}
    for voice in voices:
        lang_to_voices.setdefault(voice.language, []).append(voice)
    for vlist in lang_to_voices.values():
        vlist.sort(key=operator.attrgetter("key"))
    languages = sorted(
        lang_to_voices.keys(), key=operator.attrgetter("name_english")
    )
    return languages, lang_to_voices


@dataclasses.dataclass(frozen=True)
class InstalledListState:
    buttons_enabled: bool
    remove_enabled: bool
    is_dengjen_synth: bool


def installed_list_state(voices, synth_name: str) -> InstalledListState:
    # `remove_enabled` is deliberately not ANDed with `is_dengjen_synth`: the
    # caller only touches the remove button when a dengjen synth is active,
    # and leaves it alone otherwise.
    return InstalledListState(
        buttons_enabled=bool(voices),
        remove_enabled=len(voices) >= 2,
        is_dengjen_synth="dengjen" in synth_name.lower(),
    )


@dataclasses.dataclass(frozen=True)
class DownloadButtonState:
    std_enabled: bool
    rt_enabled: bool
    speaker_enabled: bool
    speakers: tuple


def download_button_state(voice) -> DownloadButtonState:
    multi_speaker = voice.num_speakers > 1
    return DownloadButtonState(
        std_enabled=not voice.standard_variant_installed,
        rt_enabled=voice.has_rt_variant and not voice.fast_variant_installed,
        speaker_enabled=multi_speaker,
        speakers=tuple(voice.speaker_id_map.keys()) if multi_speaker else (),
    )
