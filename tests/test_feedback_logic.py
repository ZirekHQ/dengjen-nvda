"""
Tests for feedback_logic.py: the wx-free URL construction behind the
"Send feedback" menu.
"""

import os
from urllib.parse import parse_qs, urlsplit

from tests.conftest import GLOBAL_PLUGIN_PKG_DIR, load_module_from_path

logic = load_module_from_path(
    "dengjen_tts_global_plugin._feedback_logic_under_test",
    os.path.join(GLOBAL_PLUGIN_PKG_DIR, "feedback_logic.py"),
    package="dengjen_tts_global_plugin",
)


def _parsed(url):
    split = urlsplit(url)
    return f"{split.scheme}://{split.netloc}{split.path}", parse_qs(split.query)


def test_bug_report_url_includes_all_known_versions():
    url = logic.build_bug_report_url(
        addon_version="4.0.1",
        nvda_version="2026.1",
        windows_version="Windows 11 (10.0.22631)",
    )
    base, query = _parsed(url)
    assert base == f"{logic.REPO_URL}/issues/new"
    assert query == {
        "template": ["bug_report.yml"],
        "addon-version": ["4.0.1"],
        "nvda-version": ["2026.1"],
        "windows-version": ["Windows 11 (10.0.22631)"],
    }


def test_bug_report_url_omits_unknown_versions():
    url = logic.build_bug_report_url(
        addon_version="4.0.1", nvda_version=None, windows_version=None
    )
    _, query = _parsed(url)
    assert query == {"template": ["bug_report.yml"], "addon-version": ["4.0.1"]}


def test_bug_report_url_with_no_known_versions():
    url = logic.build_bug_report_url(
        addon_version=None, nvda_version=None, windows_version=None
    )
    _, query = _parsed(url)
    assert query == {"template": ["bug_report.yml"]}


def test_feature_request_url():
    url = logic.build_feature_request_url()
    base, query = _parsed(url)
    assert base == f"{logic.REPO_URL}/issues/new"
    assert query == {"template": ["feature_request.yml"]}
