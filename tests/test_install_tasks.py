"""
Tests for installTasks.py — the uninstall hook that force-kills a leftover
dengjen-tts-grpc server process.

`_temporary_import_psutil` and therefore `onUninstall` are not exercised: they
copy the vendored psutil out of lib/ and import it, and that copy is a Windows
build (.pyd), so it cannot load on a Linux CI runner.
"""

import os

import pytest

from tests.conftest import REPO_ROOT, load_module_from_path

install_tasks = load_module_from_path(
    "_install_tasks_under_test", os.path.join(REPO_ROOT, "addon", "installTasks.py")
)

GRPC_EXE = os.path.join(install_tasks.BIN_DIR, "dengjen-tts-grpc.exe")


class _FakeProcess:
    def __init__(
        self, name, exe, pid=1, name_error=None, exe_error=None, kill_error=None
    ):
        self._name = name
        self._exe = exe
        self.pid = pid
        self.killed = False
        self._name_error = name_error
        self._exe_error = exe_error
        self._kill_error = kill_error

    def name(self):
        if self._name_error is not None:
            raise self._name_error
        return self._name

    def exe(self):
        if self._exe_error is not None:
            raise self._exe_error
        return self._exe

    def kill(self):
        if self._kill_error is not None:
            raise self._kill_error
        self.killed = True


class _FakePsutil:
    def __init__(self, processes):
        self._processes = processes
        self.waited_for = None
        self.wait_timeout = None

    def process_iter(self, attrs=None):
        return iter(self._processes)

    def wait_procs(self, processes, timeout=None):
        self.waited_for = list(processes)
        self.wait_timeout = timeout


@pytest.fixture
def samefile_by_path(monkeypatch):
    """Compare paths as strings — the real files do not exist on the runner."""
    monkeypatch.setattr(os.path, "samefile", lambda a, b: str(a) == str(b))


class TestModulePaths:
    def test_lib_and_bin_are_inside_the_synth_driver(self):
        assert install_tasks.LIB_DIR.endswith(
            os.path.join("synthDrivers", "dengjen_neural_voices", "lib")
        )
        assert install_tasks.BIN_DIR.endswith(
            os.path.join("synthDrivers", "dengjen_neural_voices", "bin")
        )

    def test_private_path_temporaries_are_cleaned_off_the_module(self):
        assert not hasattr(install_tasks, "_DIR")
        assert not hasattr(install_tasks, "_PIPER_SYNTH_DIR")


class TestForceKillDengjenGrpcServer:
    def test_kills_a_matching_server_process(self, samefile_by_path):
        proc = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE, pid=42)
        psutil = _FakePsutil([proc])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert proc.killed

    def test_matches_the_process_name_case_insensitively(self, samefile_by_path):
        proc = _FakeProcess("DENGJEN-TTS-GRPC.EXE", GRPC_EXE)
        psutil = _FakePsutil([proc])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert proc.killed

    def test_ignores_unrelated_processes(self, samefile_by_path):
        other = _FakeProcess("firefox", "/usr/bin/firefox")
        psutil = _FakePsutil([other])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert not other.killed

    def test_does_not_kill_a_same_named_exe_from_another_location(
        self, samefile_by_path
    ):
        impostor = _FakeProcess(
            "dengjen-tts-grpc.exe", "/tmp/elsewhere/dengjen-tts-grpc.exe"
        )
        psutil = _FakePsutil([impostor])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert not impostor.killed

    def test_kills_only_the_matching_process_among_several(self, samefile_by_path):
        ours = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE, pid=1)
        impostor = _FakeProcess(
            "dengjen-tts-grpc.exe", "/tmp/dengjen-tts-grpc.exe", pid=2
        )
        unrelated = _FakeProcess("bash", "/bin/bash", pid=3)
        psutil = _FakePsutil([ours, impostor, unrelated])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert ours.killed
        assert not impostor.killed
        assert not unrelated.killed

    def test_waits_on_the_name_matched_processes_with_a_timeout(self, samefile_by_path):
        ours = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE, pid=1)
        unrelated = _FakeProcess("bash", "/bin/bash", pid=2)
        psutil = _FakePsutil([ours, unrelated])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert psutil.waited_for == [ours]
        assert psutil.wait_timeout == 5

    def test_handles_there_being_no_processes_at_all(self, samefile_by_path):
        psutil = _FakePsutil([])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert psutil.waited_for == []

    def test_skips_a_process_whose_name_cannot_be_inspected(self, samefile_by_path):
        unreadable = _FakeProcess(
            "dengjen-tts-grpc.exe", GRPC_EXE, pid=1, name_error=Exception("gone")
        )
        ours = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE, pid=2)
        psutil = _FakePsutil([unreadable, ours])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert not unreadable.killed
        assert ours.killed

    def test_skips_a_process_whose_exe_cannot_be_inspected(self, samefile_by_path):
        unreadable = _FakeProcess(
            "dengjen-tts-grpc.exe", GRPC_EXE, pid=1, exe_error=Exception("gone")
        )
        ours = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE, pid=2)
        psutil = _FakePsutil([unreadable, ours])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert not unreadable.killed
        assert ours.killed

    def test_skips_a_process_whose_exe_path_no_longer_exists(self, monkeypatch):
        monkeypatch.setattr(
            os.path,
            "samefile",
            lambda a, b: (_ for _ in ()).throw(FileNotFoundError()),
        )
        proc = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE)
        psutil = _FakePsutil([proc])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert not proc.killed

    def test_one_process_failing_to_die_does_not_stop_the_others(
        self, samefile_by_path
    ):
        stubborn = _FakeProcess(
            "dengjen-tts-grpc.exe",
            GRPC_EXE,
            pid=1,
            kill_error=Exception("access denied"),
        )
        ours = _FakeProcess("dengjen-tts-grpc.exe", GRPC_EXE, pid=2)
        psutil = _FakePsutil([stubborn, ours])
        install_tasks.force_kill_dengjen_grpc_server(psutil)
        assert not stubborn.killed
        assert ours.killed
        assert psutil.waited_for == [stubborn, ours]
