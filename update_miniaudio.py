import json
import os
import shutil
import sys
import urllib.request
import zipfile

import vendored_manifest

url = "https://pypi.org/pypi/miniaudio/json"

print("Fetching miniaudio release info from PyPI...")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
except Exception as e:
    print(f"Failed to fetch PyPI data: {e}")
    sys.exit(1)


version = data["info"]["version"]
releases = data["releases"][version]

wheel_url = None
for r in releases:
    filename = r["filename"]

    if "cp313-cp313-win_amd64.whl" in filename:
        wheel_url = r["url"]
        break

if not wheel_url:
    print(
        f"Could not find a Python 3.13 64-bit Windows wheel for miniaudio version {version}."
    )
    sys.exit(1)

print(f"Downloading {wheel_url}...")
wheel_path = "miniaudio.whl"
try:
    urllib.request.urlretrieve(wheel_url, wheel_path)
except Exception as e:
    print(f"Download failed: {e}")
    sys.exit(1)

print("Extracting miniaudio...")
extract_dir = "miniaudio_extracted"
with zipfile.ZipFile(wheel_path, "r") as z:
    for info in z.infolist():
        if info.filename in ("_miniaudio.pyd", "miniaudio.py"):
            z.extract(info, extract_dir)

target_dir = os.path.join("addon", "synthDrivers", "dengjen_neural_voices", "lib")

print(f"Removing old 32-bit Python 3.11 miniaudio files from {target_dir}...")
for name in ("_miniaudio.pyd", "miniaudio.py"):
    old = os.path.join(target_dir, name)
    if os.path.exists(old):
        os.remove(old)

print(f"Installing new 64-bit Python 3.13 miniaudio to {target_dir}...")
for name in ("_miniaudio.pyd", "miniaudio.py"):
    shutil.copy(os.path.join(extract_dir, name), os.path.join(target_dir, name))

print("Cleaning up...")
os.remove(wheel_path)
shutil.rmtree(extract_dir)

vendored_manifest.record_version("miniaudio", version)

print("\nSuccessfully updated bundled miniaudio to 64-bit Python 3.13!")
print("The addon is now natively compatible with NVDA 2026.1.")
