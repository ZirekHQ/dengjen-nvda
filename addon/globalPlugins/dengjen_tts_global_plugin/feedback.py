"""Version lookups and browser hand-off for the "Send feedback" menu.

Pairs with feedback_logic.py the way voice_manager.py pairs with
voice_manager_logic.py: this module owns the NVDA/OS lookups and the side
effect (os.startfile), feedback_logic.py owns the pure URL construction.
"""

import os

import addonHandler
import gui
import wx
from logHandler import log

from .feedback_logic import build_bug_report_url, build_feature_request_url

addonHandler.initTranslation()


def _addon_version() -> str | None:
    try:
        return str(addonHandler.getCodeAddon().manifest["version"])
    except Exception:
        log.debug("Failed to determine the add-on version for feedback", exc_info=True)
        return None


def _nvda_version() -> str | None:
    try:
        import versionInfo

        return str(versionInfo.version)
    except Exception:
        log.debug("Failed to determine the NVDA version for feedback", exc_info=True)
        return None


def _windows_version() -> str | None:
    try:
        import winVersion

        return str(winVersion.getWinVer())
    except Exception:
        log.debug("Failed to determine the Windows version for feedback", exc_info=True)
        return None


def _open_url(url: str) -> None:
    try:
        os.startfile(url)
    except OSError:
        log.error(f"Failed to open the feedback URL in a browser: {url}", exc_info=True)
        gui.messageBox(
            _(
                "Couldn't open your browser automatically. "
                "Copy this link and open it manually:\n{url}"
            ).format(url=url),
            _("Dengjen Neural Voices"),
            wx.OK | wx.ICON_ERROR,
        )


def open_bug_report() -> None:
    url = build_bug_report_url(
        addon_version=_addon_version(),
        nvda_version=_nvda_version(),
        windows_version=_windows_version(),
    )
    _open_url(url)


def open_feature_request() -> None:
    _open_url(build_feature_request_url())
