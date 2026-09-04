"""Carrying downloaded voices across the 4.0.0 rename.

Two paths, because moving the folder is only safe when nobody else wants it:

  - Sonata is gone. The voices are ours; move them, retrying on every voice
    enumeration until it works (issue #83 -- the one-shot attempt from
    onInstall ran at the one moment the files were still open).
  - Sonata is still installed. Moving would break a working add-on, so leave
    the folder alone and let the voice manager copy from it on request.

Deliberately imports nothing from this package: installTasks.py loads it by
file path, which only works while it stays a leaf module.
"""

import os
import shutil

import addonHandler
import globalVars
from logHandler import log

__all__ = [
    "OLD_ADDON_NAME",
    "copy_voices_from_old_dir",
    "importable_voice_keys",
    "is_old_addon_installed",
    "migrate_voices_directory",
    "old_voices_dir",
]


OLD_ADDON_NAME = "sonata_neural_voices"
OLD_VOICES_DIR_NAME = "sonata"
VOICES_DIR_NAME = "dengjen"
_VOICES_SUBPATH = ("voices", "piper")


def _config_path(config_path=None):
    if config_path is None:
        return globalVars.appArgs.configPath
    return config_path


def old_voices_dir(config_path=None):
    return os.path.join(_config_path(config_path), OLD_VOICES_DIR_NAME)


def _voices_subdir(base_dir):
    return os.path.join(base_dir, *_VOICES_SUBPATH)


def _holds_any_file(directory):
    return any(files for _root, _dirs, files in os.walk(directory))


def is_old_addon_installed(addons=None):
    if addons is None:
        addons = addonHandler.getAvailableAddons()
    return any(
        getattr(addon, "name", None) == OLD_ADDON_NAME
        and not getattr(addon, "isPendingRemove", False)
        for addon in addons
    )


def importable_voice_keys(config_path=None):
    """Voices sitting in the pre-4.0.0 location that we do not already have."""
    old_voices = _voices_subdir(old_voices_dir(config_path))
    if not os.path.isdir(old_voices):
        return []
    new_voices = _voices_subdir(
        os.path.join(_config_path(config_path), VOICES_DIR_NAME)
    )
    return sorted(
        name
        for name in os.listdir(old_voices)
        if os.path.isdir(os.path.join(old_voices, name))
        and not os.path.isdir(os.path.join(new_voices, name))
    )


def copy_voices_from_old_dir(config_path=None):
    """Copy voices across, leaving the originals for the old add-on to use.

    Raises OSError; the caller is a dialog that reports the failure.
    """
    old_voices = _voices_subdir(old_voices_dir(config_path))
    new_voices = _voices_subdir(
        os.path.join(_config_path(config_path), VOICES_DIR_NAME)
    )
    copied = []
    for key in importable_voice_keys(config_path):
        shutil.copytree(os.path.join(old_voices, key), os.path.join(new_voices, key))
        copied.append(key)
    if copied:
        log.info(f"Copied {len(copied)} voice(s) from {old_voices}")
    return copied


def _move_tree(src, dst):
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst, name)
        if os.path.isdir(src_path) and os.path.isdir(dst_path):
            _move_tree(src_path, dst_path)
        else:
            os.rename(src_path, dst_path)
    os.rmdir(src)


def migrate_voices_directory(config_path=None, addons=None):
    """Move downloaded voices from the pre-4.0.0 location.

    Same volume, so this renames rather than copies however many GB of models
    are present.
    """
    old_dir = old_voices_dir(config_path)
    new_dir = os.path.join(_config_path(config_path), VOICES_DIR_NAME)
    if not os.path.isdir(old_dir):
        return False
    if is_old_addon_installed(addons):
        log.debug(f"Skipping voices migration: {OLD_ADDON_NAME} is still installed")
        return False

    if _holds_any_file(new_dir):
        log.debug(f"Skipping voices migration: {new_dir} already holds voices")
        return False
    try:
        _move_tree(old_dir, new_dir)
    except OSError:
        log.exception(f"Could not migrate voices from {old_dir} to {new_dir}")
        return False
    log.info(f"Migrated voices from {old_dir} to {new_dir}")
    return True
