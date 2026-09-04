# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.


import contextlib
import importlib.util
import os
import shutil
import sys
import tempfile

import addonHandler
import config
import gui
import wx
from logHandler import log

addonHandler.initTranslation()


_DIR = os.path.abspath(os.path.dirname(__file__))
_PIPER_SYNTH_DIR = os.path.join(_DIR, "synthDrivers", "dengjen_neural_voices")
LIB_DIR = os.path.join(_PIPER_SYNTH_DIR, "lib")
BIN_DIR = os.path.join(_PIPER_SYNTH_DIR, "bin")


def _load_voice_migration():
    """By file path, not import: the synth package pulls in grpc and the
    bundled Windows libraries at import time, which install must not need."""
    spec = importlib.util.spec_from_file_location(
        "_dengjen_voice_migration",
        os.path.join(_PIPER_SYNTH_DIR, "voice_migration.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voice_migration = _load_voice_migration()
del _DIR, _PIPER_SYNTH_DIR

OLD_ADDON_NAME = voice_migration.OLD_ADDON_NAME
CONFIG_SECTION = "dengjen_neural_voices"


def _as_plain_dict(section):
    return {
        key: _as_plain_dict(value) if hasattr(value, "items") else value
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


is_old_addon_installed = voice_migration.is_old_addon_installed


def warn_if_old_addon_installed(addons=None):
    if not is_old_addon_installed(addons):
        return
    wx.CallAfter(
        gui.messageBox,
        # Translators: shown after installing when the pre-rename add-on is still present
        _(
            "The Sonata Neural Voices add-on is still installed, so your downloaded "
            "voices have been left where they are and Sonata keeps working. To use "
            "them with Dengjen Neural Voices, open the Dengjen voice manager and "
            'choose "Import voices from Sonata". Removing the Sonata Neural Voices '
            "add-on also avoids two synthesizers appearing in your speech settings."
        ),
        # Translators: title of the message shown when the pre-rename add-on is still present
        _("Old add-on still installed"),
        wx.OK | wx.ICON_INFORMATION,
    )


def onInstall():
    for step in (
        warn_if_old_addon_installed,
        migrate_speech_config,
    ):
        try:
            result = step()
        except Exception:
            log.exception(f"Upgrade step {step.__name__} failed")
            continue
        if step is migrate_speech_config and result:
            try:
                config.conf.save()
            except Exception:
                log.exception("Could not save migrated speech configuration")


def onUninstall():
    with _temporary_import_psutil() as psutil:
        force_kill_dengjen_grpc_server(psutil)


def _is_dengjen_grpc_process(proc, grpc_server_exe):
    """Best-effort match: a process can exit or become inaccessible between
    enumeration and inspection, so any lookup failure here just means "not
    a match" rather than aborting the whole uninstall."""
    try:
        name = proc.name()
    except Exception:
        return False
    if not name or "dengjen-tts-grpc" not in name.lower():
        return False
    try:
        exe = proc.exe()
    except Exception:
        return False
    if not exe:
        return False
    try:
        return os.path.samefile(exe, grpc_server_exe)
    except (OSError, TypeError):
        return False


def force_kill_dengjen_grpc_server(psutil):
    log.debug("Trying to force kill GRPC server process")
    grpc_server_exe = os.path.join(BIN_DIR, "dengjen-tts-grpc.exe")
    grpc_server_processes = [
        proc
        for proc in psutil.process_iter(attrs=["name", "exe"])
        if _is_dengjen_grpc_process(proc, grpc_server_exe)
    ]
    for proc in grpc_server_processes:
        try:
            proc.kill()
            log.debug(f"Killed process with pid {proc.pid}")
        except Exception:
            log.debug(f"Failed to kill process with pid {proc.pid}", exc_info=True)
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
    try:
        import psutil

        yield psutil
    finally:
        sys.path.remove(temp_import_dir.name)
        with contextlib.suppress(Exception):
            temp_import_dir.cleanup()
