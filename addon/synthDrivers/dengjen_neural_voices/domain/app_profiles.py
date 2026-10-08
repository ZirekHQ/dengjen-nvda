# Copyright (c) 2026 Musharraf Omer, Ali Ustek, and contributors
# This file is covered by the GNU General Public License.

"""Application-specific voice profile manager for Dengjen Neural Voices."""

import contextlib
from io import StringIO

import config
from configobj import ConfigObj
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


def _is_valid_exe(exe: str) -> bool:
    return bool(exe and exe != "__many__" and not exe.startswith("__"))


def _extract_profile_data(data) -> dict:
    if hasattr(data, "dict"):
        items = data.dict().items()
    elif hasattr(data, "items") or isinstance(data, dict):
        items = data.items()
    else:
        return {}
    return {k: v for k, v in items if v is not None and not k.startswith("__")}


def _delete_target_key(target, key: str) -> None:
    underlying = None
    if hasattr(target, "_getUpdateSection"):
        with contextlib.suppress(Exception):
            underlying = target._getUpdateSection()
    if underlying is not None and hasattr(underlying, "pop"):
        underlying.pop(key, None)
    elif hasattr(target, "pop"):
        target.pop(key, None)
    elif hasattr(target, "__delitem__"):
        with contextlib.suppress(Exception):
            del target[key]
    if hasattr(target, "_cache") and isinstance(target._cache, dict):
        target._cache.pop(key, None)


def _get_app_profiles_section(profile):
    conf = profile
    for k in ("speech", "dengjen_neural_voices", "app_profiles"):
        if not hasattr(conf, "get"):
            return None
        conf = conf.get(k)
    return conf


def _delete_exe_from_profiles(profiles, exe: str) -> None:
    for p in profiles:
        with contextlib.suppress(Exception):
            p_conf = _get_app_profiles_section(p)
            if p_conf is not None and exe in p_conf:
                del p_conf[exe]
                if hasattr(config.conf, "_dirtyProfiles") and getattr(p, "name", None):
                    config.conf._dirtyProfiles.add(p.name)


def _remove_section_spec(section, exe: str) -> None:
    spec = getattr(section, "_spec", None)
    if spec is not None and hasattr(spec, "pop"):
        with contextlib.suppress(Exception):
            spec.pop(exe, None)


class AppProfileManager:
    """Manages per-application voice settings."""

    def __init__(self):
        try:
            if not config.conf["speech"].isSet("dengjen_neural_voices"):
                config.conf["speech"]["dengjen_neural_voices"] = {}
            spec = ConfigObj(
                StringIO(_PROFILE_CONFIGSPEC), list_values=False, encoding="UTF-8"
            )
            config.conf["speech"]["dengjen_neural_voices"].spec.update(spec)
        except Exception:
            log.exception(
                "Dengjen: Failed to initialize app_profiles configspec", exc_info=True
            )

    def _profiles_section(self):
        conf = config.conf["speech"]["dengjen_neural_voices"]
        if "app_profiles" not in conf:
            conf["app_profiles"] = {}
        return conf["app_profiles"]

    def _ensure_section_spec(self, section, exe: str):
        """Ensure concrete application section has a valid spec inherited from __many__."""
        if not _is_valid_exe(exe):
            return
        spec = getattr(section, "_spec", None)
        if (
            spec is not None
            and hasattr(spec, "get")
            and exe not in spec
            and "__many__" in spec
        ):
            with contextlib.suppress(Exception):
                many_spec = spec["__many__"]
                if hasattr(many_spec, "copy"):
                    spec[exe] = many_spec.copy()
                elif isinstance(many_spec, dict):
                    spec[exe] = dict(many_spec)

    def get_profile(self, exe_name: str) -> dict:
        exe = exe_name.lower()
        if not _is_valid_exe(exe):
            return {}
        section = self._profiles_section()
        self._ensure_section_spec(section, exe)
        return _extract_profile_data(section[exe]) if exe in section else {}

    def set_profile(self, exe_name: str, **kwargs):
        exe = exe_name.lower()
        if not _is_valid_exe(exe):
            return
        section = self._profiles_section()
        self._ensure_section_spec(section, exe)
        if exe not in section:
            section[exe] = {}
        target = section[exe]
        for key, value in kwargs.items():
            if value is None:
                _delete_target_key(target, key)
                if hasattr(config.conf, "_markWriteProfileDirty"):
                    with contextlib.suppress(Exception):
                        config.conf._markWriteProfileDirty()
            else:
                target[key] = value

    def delete_profile(self, exe_name: str):
        exe = exe_name.lower()
        if not _is_valid_exe(exe):
            return
        section = self._profiles_section()
        _delete_exe_from_profiles(getattr(config.conf, "profiles", []), exe)
        if hasattr(section, "_getUpdateSection"):
            with contextlib.suppress(Exception):
                update_sec = section._getUpdateSection()
                if hasattr(update_sec, "__delitem__") and exe in update_sec:
                    del update_sec[exe]
        with contextlib.suppress(Exception):
            if exe in section and hasattr(section, "__delitem__"):
                del section[exe]
        if hasattr(section, "_cache") and isinstance(section._cache, dict):
            section._cache.pop(exe, None)
        _remove_section_spec(section, exe)
        if hasattr(config.conf, "_markWriteProfileDirty"):
            with contextlib.suppress(Exception):
                config.conf._markWriteProfileDirty()

    def list_profiles(self) -> list:
        section = self._profiles_section()
        result = []
        if hasattr(section, "items"):
            for name, raw in section.items():
                if not _is_valid_exe(name):
                    continue
                data = _extract_profile_data(raw)
                result.append((name, data))
        return sorted(result, key=lambda x: x[0])

    def apply_profile_dict(self, profile: dict, synth_driver) -> bool:
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
                try:
                    synth_driver.rate = max(0, min(100, int(profile["rate"])))
                except (ValueError, TypeError):
                    log.debug(
                        "Dengjen: invalid rate in app profile: %r",
                        profile.get("rate"),
                        exc_info=True,
                    )
            if profile.get("volume") is not None:
                try:
                    synth_driver.volume = max(0, min(100, int(profile["volume"])))
                except (ValueError, TypeError):
                    log.debug(
                        "Dengjen: invalid volume in app profile: %r",
                        profile.get("volume"),
                        exc_info=True,
                    )
            if profile.get("pitch") is not None:
                try:
                    synth_driver.pitch = max(0, min(100, int(profile["pitch"])))
                except (ValueError, TypeError):
                    log.debug(
                        "Dengjen: invalid pitch in app profile: %r",
                        profile.get("pitch"),
                        exc_info=True,
                    )
            return True
        except Exception:
            log.exception("Dengjen: failed to apply profile dict")
            return False

    def apply_for_exe(self, exe_name: str, synth_driver) -> bool:
        profile = self.get_profile(exe_name)
        if not profile:
            return False
        applied = self.apply_profile_dict(profile, synth_driver)
        if applied:
            log.debug(f"Dengjen: applied app profile for '{exe_name}'")
        return applied


app_profile_manager = AppProfileManager()
