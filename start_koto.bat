@echo off
REM Koto legacy compatibility launcher.
REM Default behavior is the unified desktop app. Use an explicit "server"
REM argument only for development/debugging.
REM Usage: start_koto.bat [desktop^|server]

setlocal
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=desktop"

echo [Koto] This compatibility entry now uses the unified launcher (%MODE%).
call "%~dp0Koto_Start.bat" "%MODE%"
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
