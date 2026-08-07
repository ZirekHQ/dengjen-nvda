# coding: utf-8

# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

"""wx-free decisions behind the voice manager UI.

Imports nothing from wx, gui, winsound, miniaudio or synthDriverHandler, so
this module is importable and testable on any platform. voice_manager.py
keeps the widgets and the side effects; the branches it takes live here.
"""

from __future__ import annotations

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
