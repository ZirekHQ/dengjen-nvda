@echo off
rem Guest-side setup for scripts/vm-e2e.sh, run before every test run: root CAs, Python, VC++ runtime, e2e venv.
rem %1 = repo dir in the guest.
set PYVER=3.13.7
rem Fresh Windows lacks current root CAs until a Schannel client contacts each host; Python then trusts them.
for %%h in (www.nvaccess.org github.com huggingface.co pypi.org files.pythonhosted.org) do powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing https://%%h -TimeoutSec 30 | Out-Null}catch{}"
set PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
if not exist "%1" mkdir "%1"
if not exist "%PY%" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe -OutFile $env:TEMP\python-setup.exe"
  "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=0 Include_test=0
)
if not exist "%SystemRoot%\System32\vcruntime140_1.dll" (
  powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing https://aka.ms/vs/17/release/vc_redist.x64.exe -OutFile $env:TEMP\vc_redist.x64.exe"
  "%TEMP%\vc_redist.x64.exe" /install /quiet /norestart
)
"%PY%" -m venv "%1\.venv"
