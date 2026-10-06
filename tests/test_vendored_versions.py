"""
lib/VENDORED.txt pins must match the code vendored beside it: a Renovate bump
that edits only the pin (see update_protobuf.py) fails here until the files follow.
"""

import re
from pathlib import Path

LIB_DIR = (
    Path(__file__).resolve().parent.parent
    / "addon"
    / "synthDrivers"
    / "dengjen_neural_voices"
    / "lib"
)


def _pinned(package):
    manifest = (LIB_DIR / "VENDORED.txt").read_text(encoding="utf-8")
    match = re.search(rf"^{package}==(\S+)", manifest, re.MULTILINE)
    assert match, f"VENDORED.txt has no {package} pin"
    return match.group(1)


def _vendored_protobuf_version():
    source = (LIB_DIR / "google" / "protobuf" / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r"^__version__ = '([^']+)'", source, re.MULTILINE)
    assert match, "lib/google/protobuf/__init__.py has no __version__"
    return match.group(1)


def test_protobuf_pin_matches_vendored_files():
    pin = _pinned("protobuf")
    assert _vendored_protobuf_version() == pin, (
        f"Run `python update_protobuf.py {pin}` to refresh lib/google."
    )
