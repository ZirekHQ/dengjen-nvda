"""
Contract test for installTasks.py's uninstall-time psutil import against
the real vendored binary.

tests/test_install_tasks.py's own docstring says why it can't do this:
`_temporary_import_psutil` copies the vendored psutil out of lib/ and
imports it, and that copy is a Windows build (.pyd), so it can't load on
a Linux CI runner. This is the only place that proves it actually loads
on real Windows, and that onUninstall() kills a real running helper --
the second confirmation (alongside the abandoned-helper reaper's own
contract test) that the win_amd64 re-vendor in #118/#162 fixed both
places that import psutil, not just one.
"""

import importlib.util
import os
import subprocess
import sys
import time
import types

import espeakng_loader
import pytest

if sys.platform != "win32":
    pytest.skip(
        "dengjen-tts-grpc.exe and the vendored psutil build are Windows-only",
        allow_module_level=True,
    )

sys.modules.setdefault(
    "addonHandler",
    types.SimpleNamespace(initTranslation=lambda: None, getAvailableAddons=list),
)
sys.modules.setdefault("config", types.SimpleNamespace(conf={}))
sys.modules.setdefault("wx", types.SimpleNamespace())
sys.modules.setdefault(
    "gui", types.SimpleNamespace(messageBox=lambda *a, **k: None, mainFrame=None)
)
sys.modules.setdefault(
    "globalVars",
    types.SimpleNamespace(appArgs=types.SimpleNamespace(configPath="/tmp")),
)
sys.modules.setdefault(
    "logHandler",
    types.SimpleNamespace(
        log=types.SimpleNamespace(
            info=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )
    ),
)

from tests_contract.conftest import BIN_DIRECTORY, GRPC_SERVER_EXE, REPO_ROOT

INSTALL_TASKS_PATH = os.path.join(REPO_ROOT, "addon", "installTasks.py")
HELPER_STARTUP_GRACE = 1.0
REAP_CONFIRMATION_TIMEOUT = 5


def _load_install_tasks():
    """By file path, matching how NVDA's own addonHandler loads this
    module -- it isn't part of the dengjen_neural_voices package."""
    spec = importlib.util.spec_from_file_location(
        "_install_tasks_contract", INSTALL_TASKS_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spawn_real_helper():
    """A live dengjen-tts-grpc.exe for force_kill_dengjen_grpc_server() to
    find and kill. No need to wait for the gRPC handshake -- that
    function matches by name/exe path, not readiness."""
    env = os.environ.copy()
    env.update(
        {
            "DENGJEN_GRPC_SERVER_PORT": "0",
            "DENGJEN_ESPEAKNG_DATA_DIRECTORY": os.path.dirname(
                espeakng_loader.get_data_path()
            ),
            "DENGJEN_GRPC": "info",
        }
    )
    process = subprocess.Popen(
        args=GRPC_SERVER_EXE,
        cwd=BIN_DIRECTORY,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(HELPER_STARTUP_GRACE)
    assert process.poll() is None, "the helper exited before the test could use it"
    return process


class TestUninstallPsutilImport:
    def test_temporary_import_psutil_loads_the_real_vendored_binary(self):
        install_tasks = _load_install_tasks()
        with install_tasks._temporary_import_psutil() as psutil:
            assert psutil.pid_exists(os.getpid())

    def test_on_uninstall_kills_a_real_running_helper(self):
        install_tasks = _load_install_tasks()
        helper = _spawn_real_helper()
        try:
            install_tasks.onUninstall()

            deadline = time.monotonic() + REAP_CONFIRMATION_TIMEOUT
            while helper.poll() is None and time.monotonic() < deadline:
                time.sleep(0.1)

            assert helper.poll() is not None, "onUninstall() did not kill the helper"
        finally:
            if helper.poll() is None:
                helper.terminate()
                helper.wait(timeout=5)
