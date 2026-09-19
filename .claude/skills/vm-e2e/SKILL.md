---
name: vm-e2e
description: Run tests_e2e/ (real NVDA via nvda-addon-testkit) or any pytest target inside the local VMware Windows VM. Use to reproduce or verify NVDA behaviour (settings panels, restart, voice install) from the Linux dev host instead of reasoning from code alone.
---

# Run e2e checks on the local VMware Windows VM

Real-NVDA behaviour only exists on Windows. Reproduce it on the local VM before
concluding a bug "can't be reproduced here", and before trusting a fix.

## Run

```bash
export DENGJEN_VM_VMX="/path/to/Windows 10 x64.vmx"
export DENGJEN_VM_PASS='...'        # guest password; never commit it
scripts/vm-e2e.sh                                   # all of tests_e2e/
scripts/vm-e2e.sh tests_e2e/test_x.py -k name -s    # any pytest args
```

Get the VMX path and password from the user's handoff notes or ask; do not
write them into the repo. Optional env: `DENGJEN_VM_USER` (default `ali`),
`DENGJEN_VM_REPO`, `DENGJEN_VM_TIMEOUT` (seconds, default 1500).

The exit code is pytest's. Untracked test files run, so a throwaway probe test in
`tests_e2e/` needs no commit.

## Preconditions (the script checks the first two)

1. VM is running: `vmrun list`; otherwise `vmrun -T ws start "$DENGJEN_VM_VMX"`.
2. A user is logged in on the guest console. `-interactive` attaches to that
   session; without it `GetForegroundWindow()` is always 0. Ask the user to log
   in; do not configure autologon.
3. Guest has a repo checkout with a `.venv` (default `C:\Users\<user>\dengjen-nvda`).

## Gotchas

- `vmrun runProgramInGuest` must be given the `.bat` itself. `cmd.exe /c ...`
  exits 1 without running anything.
- If a result contradicts GitHub's Windows CI, trust CI: the VM drifts across
  restarts and re-logins. First check the baseline
  (`-k "install_is_two_phase or no_voice_modal"`); if existing tests fail the
  same way, the VM, not your change, is the problem.
- NVDA's real settings/voice panels are opened with
  `nvda.eval("__import__('wx').CallAfter(__import__('gui').mainFrame.onSpeechSettingsCommand, None)")`;
  the voice controls live on `dialog.currentCategory.voicePanel`.
