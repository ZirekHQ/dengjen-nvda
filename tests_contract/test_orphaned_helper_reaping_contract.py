"""
Contract test for the abandoned-helper reaper (#118/#160) against a real,
running dengjen-tts-grpc.exe.

The reap logic itself (matching, filtering, bounded terminate) is covered
with fake psutil/fake processes in tests/test_dengjen_grpc_backend.py --
that proves the code is correct given the process-ownership model it
assumes. This is the one place that spawns a real helper, actually lets it
go stale, and confirms initialize() kills it for real, using the real
vendored psutil build. It's also the only place that can confirm the
assumption the whole fix rests on: that DETACHED_PROCESS does not sever a
spawned dengjen-tts-grpc.exe's Windows parent-process link.
"""

import os
import shutil
import sys
import tempfile
import time
import types

import espeakng_loader
import pytest

if sys.platform != "win32":
    pytest.skip("dengjen-tts-grpc.exe is a Windows binary", allow_module_level=True)


_APP_DIR = tempfile.mkdtemp()
_SYNTH_DRIVERS_DIR = os.path.join(_APP_DIR, "synthDrivers")
shutil.copytree(
    espeakng_loader.get_data_path(), os.path.join(_SYNTH_DRIVERS_DIR, "espeak-ng-data")
)

sys.modules.setdefault(
    "globalVars",
    types.SimpleNamespace(
        appArgs=types.SimpleNamespace(configPath=tempfile.mkdtemp()), appDir=_APP_DIR
    ),
)
sys.modules.setdefault(
    "logHandler",
    types.SimpleNamespace(
        log=types.SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )
    ),
)
sys.modules.setdefault("wx", types.SimpleNamespace(GetTopLevelWindows=list))
sys.modules.setdefault(
    "gui", types.SimpleNamespace(messageBox=lambda *a, **k: None, mainFrame=None)
)
sys.modules.setdefault(
    "gui.settingsDialogs",
    types.SimpleNamespace(
        NVDASettingsDialog=type("NVDASettingsDialog", (), {}),
        SpeechSettingsPanel=type("SpeechSettingsPanel", (), {}),
    ),
)

from tests_contract.conftest import REPO_ROOT

_SYNTH_PKG_DIR = os.path.join(
    REPO_ROOT, "addon", "synthDrivers", "dengjen_neural_voices"
)
_dengjen_pkg = types.ModuleType("dengjen_neural_voices")
_dengjen_pkg.__path__ = [_SYNTH_PKG_DIR]
sys.modules.setdefault("dengjen_neural_voices", _dengjen_pkg)

import globalVars
from dengjen_neural_voices.adapters import dengjen_grpc

REAP_CONFIRMATION_TIMEOUT = 5


def _printing_log(prefix):
    def _make(level):
        def _log(msg, *args, exc_info=False, **kwargs):
            print(f"[{prefix}:{level}] {msg}")
            if exc_info:
                import traceback

                traceback.print_exc()

        return _log

    return types.SimpleNamespace(
        **{
            level: _make(level)
            for level in ("debug", "info", "warning", "error", "exception")
        }
    )


@pytest.fixture(autouse=True)
def clean_slate():
    """The gRPC helper is process-wide state shared with the other
    NVDA-stubbed contract test files in this session (they all import the
    same dengjen_grpc module). Force a known-clean start regardless of
    what ran before, and always leave it fully torn down afterward so a
    later file's session fixture gets a genuine cold start.

    logHandler is stubbed as a shared, silent no-op across every
    NVDA-stubbed contract file (sys.modules.setdefault -- whichever file
    imports first wins), which would otherwise swallow every diagnostic
    this test's reap path emits. dengjen_grpc.log is a name already bound
    at import time, so replacing it here (rather than the sys.modules
    entry) reaches this module's logging specifically, print()ing so
    pytest surfaces it in the failure's captured output. Restored
    afterward -- it's the same shared module other contract files in this
    session import too, and would otherwise leak this file's diagnostic
    printing into their tests.
    """
    original_log = dengjen_grpc.log
    dengjen_grpc.log = _printing_log("dengjen_grpc")
    try:
        dengjen_grpc.terminate()
        yield
    finally:
        dengjen_grpc.terminate()
        dengjen_grpc.log = original_log


class TestOrphanedHelperReaping:
    def test_a_prior_sessions_helper_is_reaped_on_the_next_initialize(self):
        first = dengjen_grpc.DengjenGrpcBackend()
        first.initialize()
        orphaned_process = dengjen_grpc.GRPC_SERVER_PROCESS
        orphaned_pid = orphaned_process.pid
        assert orphaned_process.poll() is None, (
            "the first helper should still be running"
        )

        # Simulate an NVDA in-process restart: the OS process -- and this
        # already-spawned, still-running child -- survives, but the
        # module's cached process/port references do not.
        del globalVars.DENGJEN_GRPC_SERVER_PORT
        del globalVars.GRPC_SERVER_PROCESS
        dengjen_grpc.GRPC_SERVER_PROCESS = None
        dengjen_grpc.DENGJEN_GRPC_SERVER_PORT = None

        second = dengjen_grpc.DengjenGrpcBackend()
        second.initialize()

        deadline = time.monotonic() + REAP_CONFIRMATION_TIMEOUT
        while orphaned_process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)

        assert orphaned_process.poll() is not None, (
            f"orphaned helper (pid {orphaned_pid}) was not reaped by initialize()"
        )
        assert dengjen_grpc.GRPC_SERVER_PROCESS.pid != orphaned_pid
