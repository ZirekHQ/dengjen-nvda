# coding: utf-8
"""
conftest.py for the stub-based test tree.

The stub apparatus itself lives in nvda_stubs.py, shared with tests_gui/
(which installs the same NVDA stubs but keeps real wxPython). Existing test
modules import REPO_ROOT / SYNTH_PKG_DIR / GLOBAL_PLUGIN_PKG_DIR /
load_module_from_path from here, so those stay re-exported.
"""

from tests.nvda_stubs import (  # noqa: F401
    GLOBAL_PLUGIN_PKG_DIR,
    REPO_ROOT,
    SYNTH_PKG_DIR,
    install,
    load_module_from_path,
)

install(stub_wx=True)
