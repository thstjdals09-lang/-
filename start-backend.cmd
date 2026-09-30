@echo off
rem AI Factory local backend: installs on first run, then opens http://127.0.0.1:8000/console/
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo [AI Factory] Creating Python environment - first run only...
  python -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install -q -e ".[dev]" || goto :error
)
".venv\Scripts\python.exe" -m app.run_local || goto :error
goto :eof

:error
echo [AI Factory] Start failed. Python 3.11+ is required: https://www.python.org/downloads/
pause
