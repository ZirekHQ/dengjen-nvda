# coding: utf-8

# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""
Application-specific voice profile manager for Dengjen Neural Voices.
"""

from collections.abc import Mapping
from io import StringIO

import config
from configobj import ConfigObj, Section
from logHandler import log

_PROFILE_CONFIGSPEC = """
[app_profiles]
[[__many__]]
voice    = string(default=None)
variant  = string(default=None)
speaker  = string(default=None)
rate     = integer(default=None, min=0, max=100)
volume   = integer(default=None, min=0, max=100)
pitch    = integer(default=None, min=0, max=100)
"""


class AppProfileManager:
    """Manages per-application voice settings."""

    def __init__(self):
        try:
            if not config.conf["speech"].isSet("dengjen_neural_voices"):
                config.conf["speech"]["dengjen_neural_voices"] = {}
            spec = ConfigObj(StringIO(_PROFILE_CONFIGSPEC), list_values=False, encoding="UTF-8")
            config.conf["speech"]["dengjen_neural_voices"].spec.update(spec)
        except Exception:
            log.exception("Dengjen: Failed to initialize app_profiles configspec", exc_info=True)

    def _profiles_section(self):
        conf = config.conf["speech"]["dengjen_neural_voices"]
        if "app_profiles" not in conf or not isinstance(conf["app_profiles"], (dict, Section, Mapping)):
            conf["app_profiles"] = {}
        return conf["app_profiles"]

    def get_profile(self, exe_name: str) -> dict:
        exe = exe_name.lower()
        section = self._profiles_section()
        if exe in section and isinstance(section[exe], (dict, Section, Mapping)):
            return dict(section[exe])
        return {}

    def set_profile(self, exe_name: str, **kwargs):
        exe = exe_name.lower()
        section = self._profiles_section()
        if exe not in section or not isinstance(section[exe], (dict, Section, Mapping)):
            section[exe] = {}
        for key, value in kwargs.items():
            if value is None:
                section[exe].pop(key, None)
            else:
                section[exe][key] = value

    def delete_profile(self, exe_name: str):
        exe = exe_name.lower()
        section = self._profiles_section()
        if exe in section:
            del section[exe]

    def list_profiles(self) -> list:
        section = self._profiles_section()
        result = []
        if hasattr(section, "items"):
            for name, data in section.items():
                if isinstance(data, (dict, Section, Mapping)):
                    result.append((name, dict(data)))
                elif hasattr(data, "items"):
                    result.append((name, {k: v for k, v in data.items()}))
        return sorted(result, key=lambda x: x[0])

    def apply_for_exe(self, exe_name: str, synth_driver) -> bool:
        profile = self.get_profile(exe_name)
        if not profile:
            return False

        try:
            if profile.get("voice") and synth_driver.voice != profile["voice"]:
                synth_driver.voice = profile["voice"]
            if profile.get("variant"):
                synth_driver.variant = profile["variant"]
            if profile.get("speaker"):
                synth_driver.speaker = profile["speaker"]
            if profile.get("rate") is not None:
                synth_driver.rate = int(profile["rate"])
            if profile.get("volume") is not None:
                synth_driver.volume = int(profile["volume"])
            if profile.get("pitch") is not None:
                synth_driver.pitch = int(profile["pitch"])
            log.debug(f"Dengjen: applied app profile for '{exe_name}'")
            return True
        except Exception:
            log.exception(f"Dengjen: failed to apply app profile for '{exe_name}'")
            return False


app_profile_manager = AppProfileManager()
