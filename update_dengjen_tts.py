"""Pins and fetches the dengjen-tts gRPC engine binary bundled into the add-on.

Usage:
    python update_dengjen_tts.py fetch           install the release pinned in dengjen-tts.lock
    python update_dengjen_tts.py bump [VERSION]  re-pin to VERSION (default: latest stable)
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

REPO = "ZirekHQ/dengjen-tts"
TAG_PREFIX = "grpc-release-v"
LOCK = Path("dengjen-tts.lock")
BIN_DIR = Path("addon/synthDrivers/dengjen_neural_voices/bin")
MARKER = BIN_DIR / ".dengjen-tts-fetched"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_RELEASE_PAGES = 10


def _get(url):
    headers = {"User-Agent": "dengjen-nvda-update", "Accept": "application/json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
        return r.read()


def read_lock(path=LOCK):
    """Returns the pinned (version, sha256) of the release zip; exits if either field is missing or malformed."""
    pairs = (
        line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
    )
    fields = {key.strip(): value.strip() for key, value in pairs}
    version, digest = fields.get("version", ""), fields.get("sha256", "")
    if not (VERSION_RE.match(version) and DIGEST_RE.match(digest)):
        raise SystemExit(f"{path}: needs 'version = X.Y.Z' and a 64-hex 'sha256 ='")
    return version, digest


def write_lock(version, digest, path=LOCK):
    path.write_text(f"version = {version}\nsha256 = {digest}\n")


def asset_url(version):
    name = f"dengjen-tts-grpc-v{version}-windows-x64.zip"
    return f"https://github.com/{REPO}/releases/download/{TAG_PREFIX}{version}/{name}"


def install(zip_bytes, bin_dir=BIN_DIR):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        (bin_dir / "dengjen-tts-grpc.exe").write_bytes(z.read("dengjen-tts-grpc.exe"))
        notice = bin_dir / "NOTICES" / "COPYING - dengjen-tts-grpc"
        notice.write_bytes(z.read("NOTICE"))


def fetch(lock=LOCK, bin_dir=BIN_DIR, marker=MARKER):
    version, digest = read_lock(lock)
    stamp = f"{version} {digest}"
    installed = (bin_dir / "dengjen-tts-grpc.exe").exists()
    if installed and marker.exists() and marker.read_text() == stamp:
        print(f"dengjen-tts-grpc {version} already installed.")
        return
    data = _get(asset_url(version))
    if (actual := hashlib.sha256(data).hexdigest()) != digest:
        raise SystemExit(
            f"sha256 mismatch for {version}: pinned {digest}, got {actual}"
        )
    install(data, bin_dir)
    marker.write_text(stamp)
    print(f"Installed dengjen-tts-grpc {version}.")


def _is_stable_grpc(release):
    tag = release["tag_name"]
    return (
        tag.startswith(TAG_PREFIX)
        and VERSION_RE.match(tag.removeprefix(TAG_PREFIX))
        and not release["draft"]
        and not release["prerelease"]
    )


def fetch_release(version):
    """Returns the release tagged for `version`, or the newest stable (non-draft, non-prerelease) grpc release with a MAJOR.MINOR.PATCH tag."""
    base = f"https://api.github.com/repos/{REPO}/releases"
    if version:
        return json.loads(_get(f"{base}/tags/{TAG_PREFIX}{version}"))
    for page in range(1, MAX_RELEASE_PAGES + 1):
        releases = json.loads(_get(f"{base}?per_page=100&page={page}"))
        if match := next(filter(_is_stable_grpc, releases), None):
            return match
        if len(releases) < 100:
            break
    raise SystemExit(f"No stable {TAG_PREFIX}* release found in {REPO}.")


def verify_digest(data, asset):
    """Exits unless the asset carries a sha256 digest that matches `data`."""
    expected = (asset.get("digest") or "").removeprefix("sha256:")
    if not DIGEST_RE.match(expected):
        raise SystemExit(f"{asset['name']}: the release publishes no sha256 digest")
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"{asset['name']}: sha256 does not match the release digest")


def bump(version, lock=LOCK):
    release = fetch_release(version)
    resolved = release["tag_name"].removeprefix(TAG_PREFIX)
    asset = next(a for a in release["assets"] if a["name"].endswith("-windows-x64.zip"))
    data = _get(asset["browser_download_url"])
    verify_digest(data, asset)
    write_lock(resolved, hashlib.sha256(data).hexdigest(), lock)
    print(f"Pinned dengjen-tts-grpc {resolved}.")


def main(argv):
    command, *rest = argv[1:] or ["fetch"]
    version = rest[0] if rest else None
    if version and not VERSION_RE.match(version):
        raise SystemExit(f"Not a MAJOR.MINOR.PATCH version: {version!r}")
    if command == "fetch":
        fetch()
    elif command == "bump":
        bump(version)
    else:
        raise SystemExit(f"Unknown command {command!r}; expected 'fetch' or 'bump'.")


if __name__ == "__main__":
    main(sys.argv)
