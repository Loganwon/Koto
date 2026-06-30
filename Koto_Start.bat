@echo off
:: Koto 统一启动器 v3.1 — BAT 入口（调用 PowerShell 主脚本）
:: 用法:
::   双击启动                → 统一桌面入口（默认）
::   Koto_Start.bat server    → 开发调试服务器（兼容）
::   Koto_Start.bat silent    → 兼容别名，等同 desktop

setlocal
cd /d "%~dp0"

:: 读取可选模式参数
set "MODE=%~1"
if "%MODE%"=="" set "MODE=desktop"
if /I "%MODE%"=="silent" set "MODE=desktop"

set "PS_SCRIPT=%~dp0Koto_Start.ps1"
if not exist "%PS_SCRIPT%" set "PS_SCRIPT=%~dp0launcher\Koto_Start.ps1"

:: 检查 PowerShell
where powershell >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 PowerShell，请安装 PowerShell 5.1+
    pause
    exit /b 1
)

if not exist "%PS_SCRIPT%" (
    echo [ERROR] 未找到启动脚本 Koto_Start.ps1
    pause
    exit /b 1
)

echo [Koto] 正在启动统一入口 (模式: %MODE%)...
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass ^
    -File "%PS_SCRIPT%" -Mode "%MODE%"

if errorlevel 1 (
    echo.
    echo [ERROR] 启动失败，请查看 logs\launcher.log 获取详情
    pause
    exit /b %errorlevel%
)
endlocal
