"""wx-free decisions behind the "Send feedback" menu.

Imports nothing from wx, gui, addonHandler, versionInfo or winVersion, so
this module is importable and testable on any platform. feedback.py keeps
the NVDA/OS lookups and the side effect (opening the browser); the URL
construction lives here.
"""

from __future__ import annotations

from urllib.parse import urlencode

REPO_URL = "https://github.com/zirekhq/dengjen-nvda"


def _issue_url(template: str, fields: dict[str, str | None]) -> str:
    params = {"template": template}
    params.update({k: v for k, v in fields.items() if v})
    return f"{REPO_URL}/issues/new?{urlencode(params)}"


def build_bug_report_url(
    addon_version: str | None,
    nvda_version: str | None,
    windows_version: str | None,
) -> str:
    return _issue_url(
        "bug_report.yml",
        {
            "addon-version": addon_version,
            "nvda-version": nvda_version,
            "windows-version": windows_version,
        },
    )


def build_feature_request_url() -> str:
    return _issue_url("feature_request.yml", {})
