@echo off
rem AI Factory public server from this PC: opens a Cloudflare tunnel and makes
rem https://thstjdals09-lang.github.io/-/ forward to it while this window stays open.
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo [AI Factory] Creating Python environment - first run only...
  python -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install -q -e ".[dev]" || goto :error
)
".venv\Scripts\python.exe" -m app.run_public || goto :error
goto :eof

:error
echo [AI Factory] Start failed. Needs Python 3.11+ and cloudflared (winget install Cloudflare.cloudflared).
pause
