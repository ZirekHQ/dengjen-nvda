#!/usr/bin/env bash
# Usage: scripts/vm-e2e.sh [pytest args]. Env and preconditions: .claude/skills/vm-e2e/SKILL.md.
set -euo pipefail

: "${DENGJEN_VM_VMX:?set DENGJEN_VM_VMX to the guest .vmx path}"
: "${DENGJEN_VM_PASS:?set DENGJEN_VM_PASS to the guest user password}"
user="${DENGJEN_VM_USER:-ali}"
repo="${DENGJEN_VM_REPO:-C:\\Users\\${user}\\dengjen-nvda}"
timeout_s="${DENGJEN_VM_TIMEOUT:-1500}"
pytest_args=("${@:-tests_e2e/}")
root="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

vm() { vmrun -T ws -gu "$user" -gp "$DENGJEN_VM_PASS" "$@" 2> >(grep -v 'AppLoader\|libaio' >&2); }
die() { echo "vm-e2e: $*" >&2; exit 2; }

vmrun list 2>/dev/null | grep -qxF "$DENGJEN_VM_VMX" \
  || die "VM not running. Start it (vmrun -T ws start \"\$DENGJEN_VM_VMX\") and log in on its console."
vm listProcessesInGuest "$DENGJEN_VM_VMX" | grep -qi "explorer.exe" \
  || die "no interactive desktop session in the guest. Log in on the VM console."

cd "$root"
# scons treats the bundle as up to date after edits inside addon/, so a stale one would be tested.
rm -f dengjen_neural_voices-*.nvda-addon
uv run --no-project --with-requirements requirements-build.txt scons >/dev/null
bundle="$(ls -t dengjen_neural_voices-*.nvda-addon | head -n1)"

{ git ls-files -co --exclude-standard | while IFS= read -r f; do [ -e "$f" ] && echo "$f"; done
  echo "$bundle"; } | zip -q "$work/src.zip" -@

guest_dir="C:\\Users\\${user}"
guest_zip="${guest_dir}\\dengjen-vm-src.zip"
guest_bat="${guest_dir}\\dengjen-vm-run.bat"
guest_log="${guest_dir}\\dengjen-vm-run.log"
guest_args="${guest_dir}\\dengjen-vm-args.txt"

printf '%s\n' "${pytest_args[@]}" >"$work/args.txt"

cat >"$work/run.bat" <<EOF
@echo off
call "${guest_dir}\\dengjen-vm-provision.bat" "${repo}" > ${guest_log} 2>&1
cd /d "${repo}"
del /q dengjen_neural_voices-*.nvda-addon 2>nul
powershell -NoProfile -Command "Remove-Item -Recurse -Force addon,tests,tests_e2e,tests_gui,tests_contract -ErrorAction SilentlyContinue; Expand-Archive -Force '${guest_zip}' ."
taskkill /F /IM nvda.exe /T >nul 2>&1
"${repo}\\.venv\\Scripts\\python.exe" -m pip install -q -r requirements-test-e2e.txt >> ${guest_log} 2>&1
if errorlevel 1 (
  echo DONE_EXIT_1>> ${guest_log}
  exit /b 1
)
"${repo}\\.venv\\Scripts\\python.exe" -m pytest @${guest_args} >> ${guest_log} 2>&1
echo DONE_EXIT_%ERRORLEVEL%>> ${guest_log}
EOF

vm deleteFileInGuest "$DENGJEN_VM_VMX" "$guest_log" >/dev/null 2>&1 || true
vm CopyFileFromHostToGuest "$DENGJEN_VM_VMX" "$work/src.zip" "$guest_zip"
sed -i "s/\$/\r/" "$work/run.bat"
vm CopyFileFromHostToGuest "$DENGJEN_VM_VMX" "$work/args.txt" "$guest_args"
sed 's/$/\r/' "$root/scripts/vm-guest-provision.bat" >"$work/provision.bat"
vm CopyFileFromHostToGuest "$DENGJEN_VM_VMX" "$work/provision.bat" "${guest_dir}\\dengjen-vm-provision.bat"
vm CopyFileFromHostToGuest "$DENGJEN_VM_VMX" "$work/run.bat" "$guest_bat"
# -interactive attaches to the console session; without it GetForegroundWindow() is always 0.
vm runProgramInGuest "$DENGJEN_VM_VMX" -interactive -noWait "$guest_bat"

deadline=$((SECONDS + timeout_s))
while ((SECONDS < deadline)); do
  sleep 5
  vm CopyFileFromGuestToHost "$DENGJEN_VM_VMX" "$guest_log" "$work/run.log" >/dev/null 2>&1 || continue
  grep -q '^DONE_EXIT_' "$work/run.log" && break
done

[ -f "$work/run.log" ] || die "no log produced within ${timeout_s}s"
cat "$work/run.log"
code="$(sed -n 's/^DONE_EXIT_\([0-9]*\).*/\1/p' "$work/run.log" | tail -n1)"
[ -n "$code" ] || die "run did not finish within ${timeout_s}s (partial log above)"
exit "$code"
