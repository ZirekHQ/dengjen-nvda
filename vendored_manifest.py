"""Shared helper for the update_*.py scripts: keeps a VENDORED.txt manifest in sync."""

import os
import re

MANIFEST_PATH = os.path.join(
    "addon", "synthDrivers", "dengjen_neural_voices", "lib", "VENDORED.txt"
)


def record_version(package, version, manifest_path=MANIFEST_PATH):
    with open(manifest_path, encoding="utf-8") as f:
        lines = f.readlines()

    pattern = re.compile(rf"^(\s*){re.escape(package)}==(\S+)(.*)$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        indent, recorded, trailer = match.groups()
        if recorded == version:
            print(f"{manifest_path}: {package} already records {version}")
            return
        lines[index] = f"{indent}{package}=={version}{trailer}\n"
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"{manifest_path}: {package} {recorded} -> {version}")
        return

    raise SystemExit(f"{manifest_path} has no {package} entry; add one first.")
