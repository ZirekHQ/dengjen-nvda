"""Refresh the vendored protobuf runtime in lib/google from the PyPI win_amd64 abi3 wheel.

Usage: python update_protobuf.py [VERSION]

Without VERSION, installs the newest release on the 4.25 line: grpcio-tools==1.62.3
generates 4.25 gencode (see update_grpc_protos.py), and 5.x rejects it.
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

import vendored_manifest

SERIES_PREFIX = "4.25."
WHEEL_SUFFIX = "-cp310-abi3-win_amd64.whl"
TARGET_DIR = os.path.join(
    "addon", "synthDrivers", "dengjen_neural_voices", "lib", "google"
)


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        return response.read()


def _version_key(version):
    return tuple(int(part) for part in version.split("."))


def pick_version(releases, requested=None):
    if requested:
        if not requested.startswith(SERIES_PREFIX):
            raise SystemExit(f"{requested} is outside the {SERIES_PREFIX}x line.")
        return requested
    stable = [v for v in releases if v.startswith(SERIES_PREFIX) and v.count(".") == 2]
    stable = [v for v in stable if all(p.isdigit() for p in v.split("."))]
    if not stable:
        raise SystemExit(f"No {SERIES_PREFIX}x release found on PyPI.")
    return max(stable, key=_version_key)


def find_wheel(files):
    for entry in files:
        if entry["filename"].endswith(WHEEL_SUFFIX):
            return entry
    raise SystemExit(f"No {WHEEL_SUFFIX} wheel in the release.")


def download_verified(entry):
    payload = _fetch(entry["url"])
    digest = hashlib.sha256(payload).hexdigest()
    if digest != entry["digests"]["sha256"]:
        raise SystemExit(f"sha256 mismatch for {entry['filename']}.")
    return payload


def install(payload):
    with tempfile.TemporaryDirectory() as tmp:
        wheel_path = os.path.join(tmp, "protobuf.whl")
        with open(wheel_path, "wb") as f:
            f.write(payload)
        with zipfile.ZipFile(wheel_path) as z:
            members = [m for m in z.namelist() if m.startswith("google/")]
            z.extractall(tmp, members)
        shutil.rmtree(TARGET_DIR, ignore_errors=True)
        shutil.copytree(os.path.join(tmp, "google"), TARGET_DIR)


def main(argv):
    requested = argv[1] if len(argv) > 1 else None
    data = json.loads(_fetch("https://pypi.org/pypi/protobuf/json"))
    version = pick_version(data["releases"], requested)
    print(f"Installing protobuf {version} into {TARGET_DIR}...")
    install(download_verified(find_wheel(data["releases"][version])))
    vendored_manifest.record_version("protobuf", version)
    print(f"Vendored protobuf is now {version}.")


if __name__ == "__main__":
    main(sys.argv)
