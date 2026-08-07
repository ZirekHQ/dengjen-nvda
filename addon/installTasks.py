# coding: utf-8

# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.


import contextlib
import os
import shutil
import sys
import tempfile

import addonHandler
import config
import globalVars
import gui
import wx
from logHandler import log

addonHandler.initTranslation()


_DIR = os.path.abspath(os.path.dirname(__file__))
_PIPER_SYNTH_DIR = os.path.join(_DIR, "synthDrivers", "dengjen_neural_voices")
LIB_DIR = os.path.join(_PIPER_SYNTH_DIR, "lib")
BIN_DIR = os.path.join(_PIPER_SYNTH_DIR, "bin")
del _DIR, _PIPER_SYNTH_DIR

OLD_ADDON_NAME = "sonata_neural_voices"
OLD_VOICES_DIR_NAME = "sonata"
VOICES_DIR_NAME = "dengjen"
CONFIG_SECTION = "dengjen_neural_voices"


def migrate_voices_directory(config_path=None):
    """Move downloaded voices from the pre-4.0.0 location. Same volume, so this
    is a rename rather than a copy however many GB of models are present."""
    if config_path is None:
        config_path = globalVars.appArgs.configPath
    old_dir = os.path.join(config_path, OLD_VOICES_DIR_NAME)
    new_dir = os.path.join(config_path, VOICES_DIR_NAME)
    if os.path.exists(new_dir) or not os.path.isdir(old_dir):
        return False
    os.rename(old_dir, new_dir)
    log.info(f"Migrated voices from {old_dir} to {new_dir}")
    return True


def _as_plain_dict(section):
    return {
        key: _as_plain_dict(value) if hasattr(value, "keys") else value
        for key, value in section.items()
    }


def migrate_speech_config(conf=None):
    """Carry rate, pitch, volume and per-language voice choices across to the
    renamed config section. The old section is left in place."""
    if conf is None:
        conf = config.conf
    speech = conf["speech"]
    if not speech.isSet(OLD_ADDON_NAME) or speech.isSet(CONFIG_SECTION):
        return False
    speech[CONFIG_SECTION] = _as_plain_dict(speech[OLD_ADDON_NAME])
    log.info(f"Migrated speech settings from {OLD_ADDON_NAME} to {CONFIG_SECTION}")
    return True


def is_old_addon_installed(addons=None):
    if addons is None:
        addons = addonHandler.getAvailableAddons()
    return any(
        getattr(addon, "name", None) == OLD_ADDON_NAME
        and not getattr(addon, "isPendingRemove", False)
        for addon in addons
    )


def warn_if_old_addon_installed(addons=None):
    if not is_old_addon_installed(addons):
        return
    wx.CallAfter(
        gui.messageBox,
        # Translators: shown after installing when the pre-rename add-on is still present
        _(
            "The Sonata Neural Voices add-on is still installed. Dengjen Neural Voices "
            "has taken over its downloaded voices, so Sonata can no longer find them. "
            "Remove the Sonata Neural Voices add-on to avoid two synthesizers appearing "
            "in your speech settings."
        ),
        # Translators: title of the message shown when the pre-rename add-on is still present
        _("Old add-on still installed"),
        wx.OK | wx.ICON_WARNING,
    )


def onInstall():
    for step in (
        warn_if_old_addon_installed,
        migrate_voices_directory,
        migrate_speech_config,
    ):
        try:
            step()
        except Exception:
            log.exception(f"Upgrade step {step.__name__} failed")


def onUninstall():
    with _temporary_import_psutil() as psutil:
        force_kill_sonata_grpc_server(psutil)


def force_kill_sonata_grpc_server(psutil):
    log.debug("Trying to force kill GRPC server process")
    grpc_server_processes = list(filter(
        lambda p: "sonata-grpc" in p.name().lower(),
        psutil.process_iter(attrs=["name", "exe"])
    ))
    grpc_server_exe = os.path.join(BIN_DIR, "sonata-grpc.exe")
    for proc in grpc_server_processes:
        if os.path.samefile(proc.exe(), grpc_server_exe):
            proc.kill()
            log.debug(f"Killed process with pid {proc.pid}")
    psutil.wait_procs(
        grpc_server_processes,
        timeout=5,
    )


@contextlib.contextmanager
def _temporary_import_psutil():
    temp_import_dir = tempfile.TemporaryDirectory()
    src = os.path.join(LIB_DIR, "psutil")
    dst = os.path.join(temp_import_dir.name, "psutil")
    shutil.copytree(src, dst)
    sys.path.insert(0, temp_import_dir.name)
    import psutil
    yield psutil
    sys.path.remove(temp_import_dir.name)
    with contextlib.suppress(Exception):
        temp_import_dir.cleanup()
