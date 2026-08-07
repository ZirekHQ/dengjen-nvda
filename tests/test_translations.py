# coding: utf-8
"""
Catalogue-level checks, plus the source-level check that the catalogue is
reached at all. No NVDA, no wx -- these run on both CI legs.

Access keys are the reason this file exists. tests_gui/ only ever sees
untranslated English, so a locale that drops the `&` from a button label takes
that button's Alt shortcut away with no visible symptom, and nothing in the
suite could catch it (#97). The .mo files NVDA actually loads are untracked
SCons output, so the tracked .po is what there is to check.

The initTranslation check below is the other half of the same blind spot: a
complete catalogue is worth nothing to a module that never binds `_` to it.
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

# The globs xgettext harvests msgids from -- buildVars.i18nSources, which the
# SCons build reads. Only one directory level deep, so vendored lib/ and the
# generated protos stay out.
_I18N_SOURCES = sorted(
    path
    for pattern in (
        "addon/globalPlugins/*/*.py",
        "addon/synthDrivers/*/*.py",
        "addon/installTasks.py",
        "buildVars.py",
    )
    for path in glob.glob(os.path.join(_REPO_ROOT, pattern))
)
_I18N_SOURCE_IDS = [os.path.relpath(path, _REPO_ROOT) for path in _I18N_SOURCES]

# `_(`, but not `foo_(`, `self._(` or `ngettext(`.
_GETTEXT_CALL = re.compile(r"(?<![\w.])_\(")


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


def _binds_gettext(source):
    """Does the module give itself a `_`, rather than inheriting NVDA's?"""
    return (
        "addonHandler.initTranslation()" in source
        or re.search(r"^from .+ import .*\b_\b", source, re.MULTILINE) is not None
    )


def test_the_i18n_sources_were_found():
    # A bad glob would parametrize nothing below and pass by testing no files.
    assert len(_I18N_SOURCES) >= 10, _I18N_SOURCE_IDS


@pytest.mark.parametrize("source_path", _I18N_SOURCES, ids=_I18N_SOURCE_IDS)
def test_every_module_with_translatable_strings_binds_its_own_gettext(source_path):
    """Regression test for #102.

    initTranslation() sets `_` on the calling module alone. Skip it and `_`
    resolves to the builtin NVDA installs, so lookups go to NVDA's catalogue
    instead of ours: our msgids are absent and the string stays English however
    complete the .po is. Nothing fails, which is why this has to be checked
    statically rather than waited for.
    """
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    if not _GETTEXT_CALL.search(source):
        pytest.skip("no translatable strings")
    assert _binds_gettext(source), (
        f"{os.path.relpath(source_path, _REPO_ROOT)} calls _() without binding it; "
        "add addonHandler.initTranslation()"
    )


def test_the_gettext_call_pattern_finds_real_calls_only():
    # Positive and negative control for _GETTEXT_CALL: a pattern that matched
    # nothing would skip every file above, and one that matched too much would
    # demand initTranslation() in modules that never translate anything.
    assert _GETTEXT_CALL.search('gui.messageBox(_("Error"))')
    assert not _GETTEXT_CALL.search("ngettext(n)")
    assert not _GETTEXT_CALL.search("self._(x)")
    assert not _GETTEXT_CALL.search("_config_path()")
