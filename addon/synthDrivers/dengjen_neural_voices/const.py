# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_PITCH",
    "DEFAULT_RATE",
    "DEFAULT_VOLUME",
    "DENGJEN_VOICES_BASE_DIR",
    "DENGJEN_VOICES_DIR",
    "FALLBACK_SPEAKER_NAME",
    "IGNORED_PUNCS",
    "PIPER_VOICES_VERSION",
]


import os

import globalVars

# An utterance is ignored if it only contains the following chars
# Eventually, this should be moved to sonata-rs
IGNORED_PUNCS = frozenset(",(){}[]`\"'")
PIPER_VOICES_VERSION = "v1.0"
DENGJEN_VOICES_BASE_DIR = os.path.join(globalVars.appArgs.configPath, "dengjen")
DENGJEN_VOICES_DIR = os.path.join(DENGJEN_VOICES_BASE_DIR, "voices", "piper")
BATCH_SIZE = max((os.cpu_count() or 2) // 2, 2)
FALLBACK_SPEAKER_NAME = "default"
DEFAULT_RATE = 50
DEFAULT_VOLUME = 100
DEFAULT_PITCH = 50
