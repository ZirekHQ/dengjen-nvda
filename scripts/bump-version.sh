#!/usr/bin/env bash
set -euo pipefail

new_version="${1:?usage: scripts/bump-version.sh <new-version>}"
if ! echo "$new_version" | grep -qE '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'; then
  echo "::error::'${new_version}' doesn't look like a semver version (X.Y.Z)" >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

old_version="$(grep -oE 'addon_version="[0-9]+\.[0-9]+\.[0-9]+"' buildVars.py | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)"
if [ -z "$old_version" ]; then
  echo "::error::Couldn't find addon_version=\"X.Y.Z\" in buildVars.py" >&2
  exit 1
fi

sed -i.bak "s/addon_version=\"${old_version}\"/addon_version=\"${new_version}\"/" buildVars.py
rm -f buildVars.py.bak

python3 -c "import ast; ast.parse(open('buildVars.py').read())"

echo "Bumped ${old_version} -> ${new_version}:"
git diff --stat -- buildVars.py
