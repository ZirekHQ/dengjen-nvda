"""Installs the third-party libraries bundled into the add-on from uv.lock.

Usage:
    python vendor_libs.py fetch    install the `vendor` dependency group into lib/
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

SCRIPT = Path(__file__)
LOCK = Path("uv.lock")
PYPROJECT = Path("pyproject.toml")
LIB_DIR = Path("addon/synthDrivers/dengjen_neural_voices/lib")
MARKER = LIB_DIR / ".vendored-libs-fetched"
NON_BUILD_TARGETS = frozenset({"pot", "mergePot"})
PYTHON_PLATFORM = "x86_64-pc-windows-msvc"
PYTHON_VERSION = "3.13"
PRUNED_DIR_NAMES = ("tests", "test", "__pycache__", "bin")
PRUNED_DIR_GLOBS = ("*.dist-info", "*.data")
PRUNED_PATHS = (
    ".lock",
    "grpc/_cython/_cygrpc/private_key_signing",
    "google/protobuf/testdata",
    "google/protobuf/internal/testing_refleaks.py",
)


def _vendor_config(pyproject):
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    relevant = {
        "groups": config.get("dependency-groups", {}),
        "uv": config.get("tool", {}).get("uv", {}),
    }
    return json.dumps(relevant, sort_keys=True).encode()


def lock_stamp(lock=LOCK, script=SCRIPT, pyproject=PYPROJECT):
    payload = lock.read_bytes() + script.read_bytes() + _vendor_config(pyproject)
    return hashlib.sha256(payload).hexdigest()


def export_requirements(run=subprocess.run):
    cmd = [
        "uv",
        "export",
        "--locked",
        "--only-group",
        "vendor",
        "--no-emit-project",
        "--format",
        "requirements-txt",
        "--no-annotate",
        "--no-header",
    ]
    return run(cmd, check=True, capture_output=True, text=True).stdout


def install_command(target):
    return [
        "uv",
        "pip",
        "install",
        "--target",
        str(target),
        "--python-platform",
        PYTHON_PLATFORM,
        "--python-version",
        PYTHON_VERSION,
        "--only-binary",
        ":all:",
        "--require-hashes",
        "--no-deps",
        "-r",
        "-",
    ]


def prune(lib_dir):
    doomed = [p for name in PRUNED_DIR_NAMES for p in lib_dir.rglob(name) if p.is_dir()]
    doomed += [p for glob in PRUNED_DIR_GLOBS for p in lib_dir.glob(glob)]
    doomed += [lib_dir / rel for rel in PRUNED_PATHS]
    for path in doomed:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


def install_cacert(lib_dir):
    shutil.copyfile(lib_dir / "certifi" / "cacert.pem", lib_dir / "cacert.pem")


def keep_cacert_license(lib_dir):
    (license_file,) = lib_dir.glob("certifi-*.dist-info/licenses/LICENSE")
    shutil.copyfile(license_file, lib_dir / "cacert.LICENSE")


def _is_current(lock, lib_dir, marker):
    populated = lib_dir.is_dir() and any(
        p.is_file() and p != marker for p in lib_dir.rglob("*")
    )
    return populated and marker.exists() and marker.read_text() == lock_stamp(lock)


def fetch(lock=LOCK, lib_dir=LIB_DIR, marker=MARKER, run=subprocess.run):
    if _is_current(lock, lib_dir, marker):
        print("Vendored libs already installed.")
        return
    try:
        requirements = export_requirements(run)
        shutil.rmtree(lib_dir, ignore_errors=True)
        run(install_command(lib_dir), input=requirements, check=True, text=True)
    except FileNotFoundError:
        raise SystemExit(
            "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
        ) from None
    keep_cacert_license(lib_dir)
    prune(lib_dir)
    install_cacert(lib_dir)
    marker.write_text(lock_stamp(lock))
    print(f"Installed vendored libs into {lib_dir}.")


def require_fetched(lock=LOCK, lib_dir=LIB_DIR, marker=MARKER):
    if not _is_current(lock, lib_dir, marker):
        raise SystemExit(
            f"{lib_dir} is missing or stale: run `python vendor_libs.py fetch`."
        )


def builds_addon(targets):
    return not targets or bool(set(targets) - NON_BUILD_TARGETS)


def main(argv):
    command = (argv[1:] or ["fetch"])[0]
    if command != "fetch":
        raise SystemExit(f"Unknown command {command!r}; expected 'fetch'.")
    fetch()


if __name__ == "__main__":
    main(sys.argv)
