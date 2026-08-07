"""Shared helper for the update_*.py scripts: keeps lib/VENDORED.txt in sync."""

import os
import re

MANIFEST_PATH = os.path.join(
    "addon", "synthDrivers", "dengjen_neural_voices", "lib", "VENDORED.txt"
)


def record_version(package, version):
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    pattern = re.compile(rf"^(\s*){re.escape(package)}==(\S+)(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        indent, recorded, trailer = match.groups()
        if recorded == version:
            print(f"{MANIFEST_PATH}: {package} already records {version}")
            return
        lines[index] = f"{indent}{package}=={version}{trailer}\n"
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"{MANIFEST_PATH}: {package} {recorded} -> {version}")
        return

    raise SystemExit(f"{MANIFEST_PATH} has no {package} entry; add one first.")
