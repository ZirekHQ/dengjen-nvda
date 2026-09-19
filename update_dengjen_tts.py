"""Vendors a dengjen-tts gRPC release into bin/ and records its version.

Usage: python update_dengjen_tts.py [VERSION]   (default: latest release)
"""

import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

import vendored_manifest

REPO = "ZirekHQ/dengjen-tts"
TAG_PREFIX = "grpc-release-v"
BIN_DIR = Path("addon/synthDrivers/dengjen_neural_voices/bin")
MANIFEST = BIN_DIR / "VENDORED.txt"
PACKAGE = "dengjen-tts-grpc"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _get(url):
    headers = {"User-Agent": "dengjen-nvda-update", "Accept": "application/json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
        return r.read()


def fetch_release(version):
    """Returns the release for `version`, or the newest stable (non-draft, non-prerelease) grpc release."""
    base = f"https://api.github.com/repos/{REPO}/releases"
    if version:
        return json.loads(_get(f"{base}/tags/{TAG_PREFIX}{version}"))
    releases = json.loads(_get(f"{base}?per_page=30"))
    stable = (r for r in releases if r["tag_name"].startswith(TAG_PREFIX))
    return next(r for r in stable if not r["draft"] and not r["prerelease"])


def pick_asset(release):
    return next(a for a in release["assets"] if a["name"].endswith("-windows-x64.zip"))


def verify_digest(data, asset):
    expected = (asset.get("digest") or "").removeprefix("sha256:")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"{asset['name']}: sha256 does not match the release digest")


def install(zip_bytes, bin_dir=BIN_DIR):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        (bin_dir / "dengjen-tts-grpc.exe").write_bytes(z.read("dengjen-tts-grpc.exe"))
        notice = bin_dir / "NOTICES" / "COPYING - dengjen-tts-grpc"
        notice.write_bytes(z.read("NOTICE"))


def main(argv):
    version = argv[1] if len(argv) > 1 else None
    if version and not VERSION_RE.match(version):
        raise SystemExit(f"Not a MAJOR.MINOR.PATCH version: {version!r}")
    release = fetch_release(version)
    resolved = release["tag_name"].removeprefix(TAG_PREFIX)
    asset = pick_asset(release)
    print(f"Downloading {asset['name']}...")
    data = _get(asset["browser_download_url"])
    verify_digest(data, asset)
    install(data)
    vendored_manifest.record_version(PACKAGE, resolved, str(MANIFEST))
    print(f"Vendored dengjen-tts-grpc {resolved}.")


if __name__ == "__main__":
    main(sys.argv)
