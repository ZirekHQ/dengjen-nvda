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

import ast
import glob
import os
import re

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_CATALOGUES = sorted(
    glob.glob(
        os.path.join(_REPO_ROOT, "addon", "locale", "*", "LC_MESSAGES", "nvda.po")
    )
)
_LOCALES = [path.split(os.sep)[-3] for path in _CATALOGUES]






_I18N_SOURCES = sorted(
    path
    for pattern in (
        "addon/globalPlugins/*/*.py",
        "addon/synthDrivers/*/*.py",
        "addon/synthDrivers/*/domain/*.py",
        "addon/synthDrivers/*/ports/*.py",
        "addon/synthDrivers/*/adapters/*.py",
        "addon/synthDrivers/*/adapters/*/*.py",
        "addon/installTasks.py",
        "buildVars.py",
    )
    for path in glob.glob(os.path.join(_REPO_ROOT, pattern))
)
_I18N_SOURCE_IDS = [os.path.relpath(path, _REPO_ROOT) for path in _I18N_SOURCES]


_GETTEXT_CALL = re.compile(r"(?<![\w.])_\(")


def _po_string(token):
    
    
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
                raise AssertionError(
                    f"{path}:{lineno}: unhandled po construct {line!r}"
                )
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
    
    match = re.search(r"&(\w)", text.replace("&&", ""))
    return match.group(1).lower() if match else None


def test_the_catalogues_were_found():
    
    
    assert _LOCALES, f"no catalogues under {_REPO_ROOT}/addon/locale"


@pytest.mark.parametrize("catalogue", _CATALOGUES, ids=_LOCALES)
def test_translations_neither_drop_nor_invent_access_keys(catalogue):
    translated = [
        (msgid, msgstr)
        for msgid, msgstr in _po_entries(catalogue)
        if msgid and msgstr  
    ]
    
    
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





_INSTALLED_TAB_LABELS = (
    "&Voice model card...",
    "&Remove voice...",
    "&Install from local file",
    "Import voices from &Sonata",
    "&Close",
)


@pytest.mark.parametrize("catalogue", _CATALOGUES, ids=_LOCALES)
def test_translated_access_keys_do_not_collide_on_the_installed_tab(catalogue):
    """tests_gui/ only ever sees English, so a collision a translator
    introduces is invisible to it -- and finding a free letter is not the same
    problem in every language. French cannot mirror the English `&Sonata`:
    `&Supprimer la voix...` already claims its `s` (#108).
    """
    entries = dict(_po_entries(catalogue))
    drifted = [label for label in _INSTALLED_TAB_LABELS if label not in entries]
    assert not drifted, f"this list no longer matches the catalogue: {drifted}"

    claimed = {}
    for label in _INSTALLED_TAB_LABELS:
        key = _access_key(entries[label])
        if key is not None:  
            claimed.setdefault(key, []).append(entries[label])
    
    assert len(claimed) >= 3, claimed
    collisions = {key: labels for key, labels in claimed.items() if len(labels) > 1}
    assert not collisions, f"Alt is ambiguous: {collisions}"


def _binds_gettext(source):
    """Does the module give itself a `_`, rather than inheriting NVDA's?"""
    return (
        "addonHandler.initTranslation()" in source
        or re.search(r"^from .+ import .*\b_\b", source, re.MULTILINE) is not None
    )


def test_the_i18n_sources_were_found():
    
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


_PO_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


def _unescape(text):
    """po escapes -> the real string, so it can be compared to the source.

    Unknown escapes raise rather than pass through: silently mangling one
    would show up as a spurious drift failure with no clue why.
    """
    out, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            out.append(_PO_ESCAPES[text[index + 1]])
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _source_msgids(path):
    """Every `_("literal")` in `path`. Not `_(variable)` -- xgettext cannot see
    those either, so they are a separate bug from the one checked here."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


_SOURCE_MSGIDS = set().union(*(_source_msgids(path) for path in _I18N_SOURCES))


@pytest.mark.parametrize("catalogue", _CATALOGUES, ids=_LOCALES)
def test_catalogues_carry_exactly_the_msgids_the_source_uses(catalogue):
    """Regression test for #105.

    `scons pot` regenerates the .pot but nothing merges it into the tracked
    .po files, so strings added since a locale was last touched were never
    offered to its translator and rendered in English. Eleven had built up,
    plus a changelog entry still describing 3.x.
    """
    assert len(_SOURCE_MSGIDS) >= 50, "the source extractor found almost nothing"
    catalogued = {_unescape(msgid) for msgid, _ in _po_entries(catalogue) if msgid}
    missing = sorted(_SOURCE_MSGIDS - catalogued)
    orphaned = sorted(catalogued - _SOURCE_MSGIDS)
    assert not missing, f"strings no translator has been offered: {missing}"
    assert not orphaned, f"catalogued strings the source no longer uses: {orphaned}"


def test_the_gettext_call_pattern_finds_real_calls_only():
    
    
    
    assert _GETTEXT_CALL.search('gui.messageBox(_("Error"))')
    assert not _GETTEXT_CALL.search("ngettext(n)")
    assert not _GETTEXT_CALL.search("self._(x)")
    assert not _GETTEXT_CALL.search("_config_path()")
