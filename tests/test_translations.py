# coding: utf-8
"""
Catalogue-level checks. No NVDA, no wx -- these run on both CI legs.

Access keys are the reason this file exists. tests_gui/ only ever sees
untranslated English, so a locale that drops the `&` from a button label takes
that button's Alt shortcut away with no visible symptom, and nothing in the
suite could catch it (#97). The .mo files NVDA actually loads are untracked
SCons output, so the tracked .po is what there is to check.
"""

import glob
import os
import re

import pytest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_CATALOGUES = sorted(
    glob.glob(os.path.join(_REPO_ROOT, "addon", "locale", "*", "LC_MESSAGES", "nvda.po"))
)
_LOCALES = [path.split(os.sep)[-3] for path in _CATALOGUES]


def _po_string(token):
    # Escapes are left as they are: this file only ever inspects `&`, and po
    # never escapes that.
    assert token.startswith('"'), token
    assert token.endswith('"'), token
    return token[1:-1]


def _po_entries(path):
    """Yield (msgid, msgstr) for every entry in `path`.

    Strict about what it has not been taught: these catalogues carry no plural
    forms, fuzzy flags or obsolete entries, and a parser that skipped one
    silently would turn a real regression into a pass.
    """
    field = None
    msgid = msgstr = ""
    with open(path, encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if line.startswith(("msgid_plural", "msgstr[", "#~")):
                raise AssertionError(f"{path}:{lineno}: unhandled po construct {line!r}")
            if line.startswith("msgid "):
                if field is not None:
                    yield msgid, msgstr
                msgid, msgstr = _po_string(line[len("msgid ") :]), ""
                field = "msgid"
            elif line.startswith("msgstr "):
                msgstr = _po_string(line[len("msgstr ") :])
                field = "msgstr"
            elif line.startswith('"') and field is not None:
                if field == "msgid":
                    msgid += _po_string(line)
                else:
                    msgstr += _po_string(line)
    if field is not None:
        yield msgid, msgstr


def _access_key(text):
    """The Alt shortcut `text` claims, lowercased, or None."""
    # && is a literal ampersand, not a mnemonic marker.
    match = re.search(r"&(\w)", text.replace("&&", ""))
    return match.group(1).lower() if match else None


def test_the_catalogues_were_found():
    # Without this, a bad glob would silently parametrize nothing below and the
    # whole file would pass by testing zero locales.
    assert _LOCALES, f"no catalogues under {_REPO_ROOT}/addon/locale"


@pytest.mark.parametrize("catalogue", _CATALOGUES, ids=_LOCALES)
def test_translations_neither_drop_nor_invent_access_keys(catalogue):
    translated = [
        (msgid, msgstr)
        for msgid, msgstr in _po_entries(catalogue)
        if msgid and msgstr  # skip the header entry and untranslated strings
    ]
    # positive control: a parser that returned nothing useful would otherwise
    # make every locale look clean.
    assert sum(1 for msgid, _ in translated if _access_key(msgid)) >= 5

    dropped = [
        (msgid, msgstr)
        for msgid, msgstr in translated
        if _access_key(msgid) and not _access_key(msgstr)
    ]
    invented = [
        (msgid, msgstr)
        for msgid, msgstr in translated
        if _access_key(msgstr) and not _access_key(msgid)
    ]
    assert not dropped, f"translations lost their access key: {dropped}"
    assert not invented, f"translations added an access key: {invented}"
