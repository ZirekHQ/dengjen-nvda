"""Locates the NAIST-jdic install for the engine.

The engine reads DENGJEN_JA_DICT_DIR only at startup, so it must be set in the
spawn environment. A user-set value wins.
"""

from pathlib import Path

DICTIONARY_ENV = "DENGJEN_JA_DICT_DIR"


def is_installed(dictionary_dir):
    return (Path(dictionary_dir) / "metadata.json").is_file()


def engine_environment(dictionary_dir, existing_env):
    if existing_env.get(DICTIONARY_ENV) or not is_installed(dictionary_dir):
        return {}
    return {DICTIONARY_ENV: str(dictionary_dir)}
