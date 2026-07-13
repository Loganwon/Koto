@echo off
REM Koto Server Launcher
REM Ensures the correct venv Python is used, not any system Python.
REM Usage: start_koto.bat

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r config\requirements.txt
    pause
    exit /b 1
)

echo [Koto] Starting server with .venv Python...
.venv\Scripts\python.exe -m web.app
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Server exited with code %ERRORLEVEL%
    pause
)
endlocal
