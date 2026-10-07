import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vendor_libs as vendor


class FakeRun:
    def __init__(self, lib_dir):
        self.lib_dir = lib_dir
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[:2] == ["uv", "export"]:
            return type("R", (), {"stdout": "grpcio==1.0 --hash=sha256:aa\n"})()
        (self.lib_dir / "grpc").mkdir(parents=True, exist_ok=True)
        (self.lib_dir / "grpc" / "__init__.py").write_text("")
        (self.lib_dir / "grpcio-1.0.dist-info").mkdir(exist_ok=True)
        (self.lib_dir / "pkg" / "tests").mkdir(parents=True, exist_ok=True)
        (self.lib_dir / "pkg" / "__pycache__").mkdir(exist_ok=True)
        (self.lib_dir / "bin").mkdir(exist_ok=True)
        (self.lib_dir / "certifi").mkdir(exist_ok=True)
        (self.lib_dir / "certifi" / "cacert.pem").write_text("PEM")
        (self.lib_dir / ".lock").write_text("")
        licenses = self.lib_dir / "certifi-1.0.dist-info" / "licenses"
        licenses.mkdir(parents=True, exist_ok=True)
        (licenses / "LICENSE").write_text("MPL")
        return type("R", (), {"stdout": ""})()


@pytest.fixture
def env(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("lock-v1")
    lib = tmp_path / "lib"
    return lock, lib, lib / ".vendored-libs-fetched"


def test_fetch_copies_certifi_bundle_to_lib_root(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    assert (lib / "cacert.pem").read_text() == "PEM"


def test_fetch_keeps_certifi_license_and_drops_uv_lock_file(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    assert (lib / "cacert.LICENSE").read_text() == "MPL"
    assert not (lib / ".lock").exists()


def test_export_requirements_fails_on_lock_drift_instead_of_re_resolving():
    seen = []

    def capture(cmd, **kwargs):
        seen.append(cmd)
        return type("R", (), {"stdout": ""})()

    vendor.export_requirements(capture)
    assert "--locked" in seen[0]


def test_stamp_changes_when_the_fetch_script_changes(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("lock")
    script_a, script_b = tmp_path / "a.py", tmp_path / "b.py"
    script_a.write_text("PRUNED = 1")
    script_b.write_text("PRUNED = 2")
    assert vendor.lock_stamp(lock, script_a) != vendor.lock_stamp(lock, script_b)


def test_install_command_targets_windows_cp313_with_hashes(tmp_path):
    cmd = vendor.install_command(tmp_path / "lib")
    assert cmd[:3] == ["uv", "pip", "install"]
    for flag in ("--require-hashes", "--no-deps", "--only-binary"):
        assert flag in cmd
    assert cmd[cmd.index("--python-platform") + 1] == "x86_64-pc-windows-msvc"
    assert cmd[cmd.index("--python-version") + 1] == "3.13"
    assert cmd[cmd.index("--target") + 1] == str(tmp_path / "lib")


def test_fetch_installs_prunes_and_writes_marker(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    assert (lib / "grpc" / "__init__.py").exists()
    assert not (lib / "grpcio-1.0.dist-info").exists()
    assert not (lib / "pkg" / "tests").exists()
    assert not (lib / "pkg" / "__pycache__").exists()
    assert not (lib / "bin").exists()
    assert marker.read_text() == vendor.lock_stamp(lock)


def test_fetch_skips_when_marker_matches_and_lib_populated(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    run = FakeRun(lib)
    vendor.fetch(lock, lib, marker, run)
    assert run.calls == []


def test_fetch_reinstalls_when_lib_was_deleted_but_marker_remains(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    for entry in lib.iterdir():
        if entry == marker:
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    run = FakeRun(lib)
    vendor.fetch(lock, lib, marker, run)
    assert run.calls != []


def test_fetch_reinstalls_into_a_clean_lib_when_lock_changes(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    (lib / "stale.py").write_text("")
    lock.write_text("lock-v2")
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    assert not (lib / "stale.py").exists()
    assert marker.read_text() == vendor.lock_stamp(lock)


def test_fetch_exits_with_a_message_when_uv_is_missing(env):
    lock, lib, marker = env

    def no_uv(cmd, **kwargs):
        raise FileNotFoundError("uv")

    with pytest.raises(SystemExit, match="uv"):
        vendor.fetch(lock, lib, marker, no_uv)


def test_main_rejects_unknown_command():
    with pytest.raises(SystemExit, match="fetch"):
        vendor.main(["vendor_libs.py", "bogus"])


def test_require_fetched_names_the_fetch_command_when_lib_is_missing(env):
    lock, lib, marker = env
    with pytest.raises(SystemExit, match=r"vendor_libs\.py fetch"):
        vendor.require_fetched(lock, lib, marker)


def test_require_fetched_passes_after_a_fetch(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    vendor.require_fetched(lock, lib, marker)


def test_require_fetched_rejects_a_marker_from_an_older_lock(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    lock.write_text("lock-v2")
    with pytest.raises(SystemExit, match=r"vendor_libs\.py fetch"):
        vendor.require_fetched(lock, lib, marker)


def test_require_fetched_rejects_a_marker_over_an_empty_lib(env):
    lock, lib, marker = env
    vendor.fetch(lock, lib, marker, FakeRun(lib))
    for entry in lib.iterdir():
        if entry != marker:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    with pytest.raises(SystemExit, match=r"vendor_libs\.py fetch"):
        vendor.require_fetched(lock, lib, marker)


def _stamp(tmp_path, pyproject):
    names = ("uv.lock", "s.py", "pyproject.toml")
    lock, script, project = (tmp_path / name for name in names)
    lock.write_text("lock")
    script.write_text("script")
    project.write_text(pyproject)
    return vendor.lock_stamp(lock, script, project)


VENDOR_GROUP = '[dependency-groups]\nvendor = ["grpcio"]\n'


def test_stamp_changes_when_the_vendor_group_changes(tmp_path):
    before = _stamp(tmp_path, VENDOR_GROUP)
    after = _stamp(tmp_path, '[dependency-groups]\nvendor = ["grpcio", "idna"]\n')
    assert before != after


def test_stamp_ignores_unrelated_pyproject_sections(tmp_path):
    before = _stamp(tmp_path, VENDOR_GROUP)
    after = _stamp(tmp_path, VENDOR_GROUP + "[tool.ruff]\nline-length = 99\n")
    assert before == after


@pytest.mark.parametrize(
    ("targets", "needs_lib"),
    [
        ([], True),
        (["pot"], False),
        (["pot", "mergePot"], False),
        (["dengjen_neural_voices-4.1.0.nvda-addon"], True),
        (["pot", "dengjen_neural_voices-4.1.0.nvda-addon"], True),
    ],
)
def test_builds_addon_only_for_targets_that_package_it(targets, needs_lib):
    assert vendor.builds_addon(targets) is needs_lib
