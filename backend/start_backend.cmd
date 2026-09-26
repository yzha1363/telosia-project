@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Missing backend\.venv. See README.md for local setup.
    exit /b 1
)
if not exist ".env" (
    echo Missing backend\.env. Copy .env.example and configure it locally.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_local_backend.py" %*
exit /b %errorlevel%
