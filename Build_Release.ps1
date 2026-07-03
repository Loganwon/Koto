#Requires -Version 5.1
<#
.SYNOPSIS
    Koto 一键打包发布脚本
.DESCRIPTION
    功能：
      1. 运行 PyInstaller 构建 Koto.exe（dist/Koto/）
      2. 运行 deploy_portable.py 组装便携包（dist/Koto_Portable/）
      3. 将便携包压缩为带版本号的 zip（dist/Koto_v*.zip）

    使用方法：
      .\Build_Release.ps1                    # 正常构建（含 --clean，完整重建）
      .\Build_Release.ps1 -Incremental       # 增量构建：跳过 --clean，只重编译变更的 .py
      .\Build_Release.ps1 -SkipBuild         # 跳过 PyInstaller，直接重打包（仅资源/配置变动时用）
      .\Build_Release.ps1 -Version "1.2.0"   # 指定版本号（默认读根目录 VERSION 文件）

    常见问题：
      - ModuleNotFoundError  → 在 koto.spec 的 hiddenimports 里补模块名
      - 找不到资源文件        → 在 koto.spec 的 datas 里补路径
      - 启动崩溃无提示       → 查看 logs/ 目录的日志文件
#>

param(
    [switch]$SkipBuild,
    [switch]$SkipCython,
    [switch]$Incremental,   # 增量构建：不加 --clean，保留上次缓存（只改了 .py 时快很多）
    [string]$Version = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_ROOT  = $PSScriptRoot
$VENV_PIP   = Join-Path $REPO_ROOT ".venv\Scripts\pyinstaller.exe"
$DEPLOY_PY  = Join-Path $REPO_ROOT "src\deploy_portable.py"
$PYTHON     = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$DIST_DIR   = Join-Path $REPO_ROOT "dist"
$LOG_DIR    = Join-Path $REPO_ROOT "logs"
$SPEC_FILE  = Join-Path $REPO_ROOT "koto.spec"
$LOCAL_INSTALLER_SPEC = Join-Path $REPO_ROOT "local_model_installer.spec"

# ─── 颜色输出辅助 ─────────────────────────────
function Write-Step  { param([string]$msg) Write-Host "`n[$([char]0x25B6)] $msg" -ForegroundColor Cyan }
function Write-OK    { param([string]$msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail  { param([string]$msg) Write-Host "  [!!] $msg" -ForegroundColor Red }

function Invoke-CmdLogged {
    param(
        [Parameter(Mandatory = $true)][string]$CommandLine,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $cmdExe = if ($env:ComSpec) { $env:ComSpec } else { "cmd.exe" }
    $redirected = '{0} > "{1}" 2>&1' -f $CommandLine, $LogPath
    & $cmdExe /d /c $redirected
    return $LASTEXITCODE
}

function Invoke-ProcessLogged {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $stdoutLog = "$LogPath.stdout"
    $stderrLog = "$LogPath.stderr"
    Remove-Item $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

    $proc = Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -Wait `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog

    $parts = @()
    if (Test-Path $stdoutLog) {
        $parts += Get-Content $stdoutLog -Raw -ErrorAction SilentlyContinue
    }
    if (Test-Path $stderrLog) {
        $parts += Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue
    }

    $content = ($parts | Where-Object { -not [string]::IsNullOrEmpty($_) }) -join [Environment]::NewLine
    Set-Content -Path $LogPath -Value $content -Encoding UTF8
    Remove-Item $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
    return $proc.ExitCode
}

function Format-CmdArg {
    param([Parameter(Mandatory = $true)][string]$Value)

    return '"{0}"' -f $Value.Replace('"', '""')
}

function Get-UniverIndexAssetRefs {
    param([Parameter(Mandatory = $true)][string]$IndexHtmlPath)

    $content = Get-Content $IndexHtmlPath -Raw -Encoding UTF8
    $jsMatch = [regex]::Match($content, "(assets/index-[^`"'>]+\.js)")
    $cssMatch = [regex]::Match($content, "(assets/index-[^`"'>]+\.css)")
    if (-not $jsMatch.Success) {
        throw "未在 $IndexHtmlPath 中找到 index-*.js 引用"
    }
    if (-not $cssMatch.Success) {
        throw "未在 $IndexHtmlPath 中找到 index-*.css 引用"
    }

    return @($jsMatch.Groups[1].Value, $cssMatch.Groups[1].Value)
}

function Test-WorkspaceStaticAssets {
    param(
        [Parameter(Mandatory = $true)][string]$StaticRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $required = @(
        (Join-Path $StaticRoot "js\build\workspace-bundle.js"),
        (Join-Path $StaticRoot "jszip.min.js"),
        (Join-Path $StaticRoot "docx-preview.min.js"),
        (Join-Path $StaticRoot "univer-dist\index.html"),
        (Join-Path $StaticRoot "univer-dist\assets\sheets-main.js"),
        (Join-Path $StaticRoot "univer-dist\assets\sheets-main.css")
    )

    foreach ($path in $required) {
        if (-not (Test-Path $path)) {
            throw "$Label 缺少关键静态资源: $path"
        }
    }

    $indexHtml = Join-Path $StaticRoot "univer-dist\index.html"
    $indexDir = Split-Path $indexHtml -Parent
    foreach ($asset in Get-UniverIndexAssetRefs -IndexHtmlPath $indexHtml) {
        $assetPath = Join-Path $indexDir $asset
        if (-not (Test-Path $assetPath)) {
            throw "$Label 缺少 index.html 引用的资源: $assetPath"
        }
    }

    Write-OK "$Label 关键静态资源齐全"
}

function Test-PackagedConfigDefaults {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $required = @(
        (Join-Path $ConfigRoot ".builtin_key"),
        (Join-Path $ConfigRoot "gemini_config.env.example"),
        (Join-Path $ConfigRoot "macro_suggestions.json"),
        (Join-Path $ConfigRoot "personality_matrix.json"),
        (Join-Path $ConfigRoot "skill_affinity.json"),
        (Join-Path $ConfigRoot "skill_bindings.json"),
        (Join-Path $ConfigRoot "skill_ratings.json"),
        (Join-Path $ConfigRoot "triggers.json"),
        (Join-Path $ConfigRoot "context"),
        (Join-Path $ConfigRoot "divination_data"),
        (Join-Path $ConfigRoot "skills"),
        (Join-Path $ConfigRoot "skill_packs"),
        (Join-Path $ConfigRoot "tools"),
        (Join-Path $ConfigRoot "workflows")
    )

    foreach ($path in $required) {
        if (-not (Test-Path $path)) {
            throw "$Label 缺少关键默认配置: $path"
        }
    }

    Write-OK "$Label 关键默认配置齐全"
}

function Set-PackagedConfigDirectories {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $requiredDirs = @(
        "context",
        "divination_data",
        "skills",
        "skill_packs",
        "tools",
        "workflows"
    )

    foreach ($dirName in $requiredDirs) {
        $path = Join-Path $ConfigRoot $dirName
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
            Write-Host "  [--] 已补齐 $Label 目录: $dirName" -ForegroundColor Yellow
        }
    }
}

# ─── 前置检查 ────────────────────────────────
Write-Step "前置检查"
if (-not (Test-Path $VENV_PIP)) {
    Write-Fail "找不到 .venv\Scripts\pyinstaller.exe，请先运行：python -m venv .venv ; .\.venv\Scripts\pip install -r config\requirements.txt"
    exit 1
}
if (-not (Test-Path $PYTHON)) {
    Write-Fail "找不到 .venv\Scripts\python.exe"
    exit 1
}
if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR | Out-Null }
Write-OK "虚拟环境 OK"

# ─── 版本号（单一来源：根目录 VERSION 文件）──────────
if ([string]::IsNullOrWhiteSpace($Version)) {
    $versionFile = Join-Path $REPO_ROOT "VERSION"
    if (Test-Path $versionFile) {
        $Version = (Get-Content $versionFile -Raw).Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = Get-Date -Format "yyyy.MM.dd" }
Write-OK "版本号: $Version"

# ─── 步骤 0：Cython 编译（保护核心模块 + _license key）────
if ($SkipCython) {
    Write-Step "步骤 0/5  跳过 Cython 编译（-SkipCython）"
} else {
    Write-Step "步骤 0/5  Cython 编译核心模块 → .pyd（保护源码 + 内嵌 Key）"
    $cythonLog = Join-Path $LOG_DIR "cython_build.log"
    $cythonExitCode = Invoke-CmdLogged -CommandLine ('{0} {1} build_ext --inplace' -f (Format-CmdArg $PYTHON), (Format-CmdArg (Join-Path $REPO_ROOT "build_cython.py"))) -LogPath $cythonLog
    if ($cythonExitCode -ne 0) {
        Write-Fail "Cython 编译失败，查看日志：$cythonLog"
        Get-Content $cythonLog -Tail 20
        exit 1
    }
    Write-OK "Cython 编译完成（_license.pyd 及核心模块 .pyd 已生成）"
}

# ─── 步骤 0.5：前端资产构建（Vite + esbuild） ──────────
Write-Step "步骤 0.5  前端资产构建（文件助手 + Univer Sheets）"
$univDir = Join-Path $REPO_ROOT "web\univer-editor"
$staticRoot = Join-Path $REPO_ROOT "web\static"
$frontendInstallLog = Join-Path $LOG_DIR "frontend_npm_ci.log"
$frontendBuildLog = Join-Path $LOG_DIR "frontend_build.log"

# 检测 Node.js / npm 是否可用
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if ($nodeCmd -and $npmCmd) {
    $npmExecutable = if ($npmCmd.Source -match '\.cmd$') {
        $npmCmd.Source
    } elseif (Test-Path ($npmCmd.Source + '.cmd')) {
        $npmCmd.Source + '.cmd'
    } else {
        $npmCmd.Source
    }

    Push-Location $univDir
    try {
        if (-not (Test-Path (Join-Path $univDir "node_modules"))) {
            Write-Step "  [npm] 安装文件助手前端依赖..."
            $npmExitCode = Invoke-ProcessLogged -FilePath $npmExecutable -ArgumentList @('ci') -WorkingDirectory $univDir -LogPath $frontendInstallLog
            if ($npmExitCode -ne 0) {
                Write-Fail "npm ci 失败，查看日志：$frontendInstallLog"
                Get-Content $frontendInstallLog -Tail 40
                exit 1
            }
            Write-OK "前端依赖安装完成"
        }

        Write-Step "  [npm] 构建文件助手前端资源..."
        $npmExitCode = Invoke-ProcessLogged -FilePath $npmExecutable -ArgumentList @('run', 'build') -WorkingDirectory $univDir -LogPath $frontendBuildLog
        if ($npmExitCode -ne 0) {
            Write-Fail "npm run build 失败，查看日志：$frontendBuildLog"
            Get-Content $frontendBuildLog -Tail 60
            exit 1
        }
        Write-OK "前端构建完成"
    } finally { Pop-Location }
} else {
    # Node.js 不可用 — 检查预构建产物是否存在
    Write-Host "  [--] 未检测到 Node.js/npm，检查预构建资产..." -ForegroundColor Yellow
    if (-not (Test-Path (Join-Path $staticRoot "univer-dist\index.html"))) {
        Write-Fail "前端预构建资产缺失且无 Node.js 可用！请安装 Node.js 或手动构建前端。"
        exit 1
    }
    Write-Host "  [OK] 预构建资产已存在，跳过前端构建" -ForegroundColor Green
}

Test-WorkspaceStaticAssets -StaticRoot $staticRoot -Label "源代码前端产物"

# ─── 步骤 1：PyInstaller 构建 ─────────────────
if (-not $SkipBuild) {
    $buildLog = Join-Path $LOG_DIR "build_latest.log"
    if ($Incremental) {
        Write-Step "步骤 1/5  PyInstaller 增量构建（无 --clean，输出日志至 logs\build_latest.log）"
        $pyInstallerExitCode = Invoke-CmdLogged -CommandLine ('{0} {1} -y' -f (Format-CmdArg $VENV_PIP), (Format-CmdArg $SPEC_FILE)) -LogPath $buildLog
    } else {
        Write-Step "步骤 1/5  PyInstaller 完整构建（--clean，输出日志至 logs\build_latest.log）"
        $pyInstallerExitCode = Invoke-CmdLogged -CommandLine ('{0} {1} --clean -y' -f (Format-CmdArg $VENV_PIP), (Format-CmdArg $SPEC_FILE)) -LogPath $buildLog
    }
    if ($pyInstallerExitCode -ne 0) {
        Write-Fail "PyInstaller 失败，查看详细日志：$buildLog"
        Write-Host "(最后 30 行)" -ForegroundColor Yellow
        Get-Content $buildLog -Tail 30
        exit 1
    }
    Write-OK "构建完成 → dist\Koto\Koto.exe"
    Test-WorkspaceStaticAssets -StaticRoot (Join-Path $DIST_DIR "Koto\_internal\web\static") -Label "PyInstaller 包内前端产物"
    Set-PackagedConfigDirectories -ConfigRoot (Join-Path $DIST_DIR "Koto\_internal\config") -Label "PyInstaller 包内默认配置"
    Test-PackagedConfigDefaults -ConfigRoot (Join-Path $DIST_DIR "Koto\_internal\config") -Label "PyInstaller 包内默认配置"
} else {
    Write-Step "跳过 PyInstaller（-SkipBuild）"
}

# ─── 步骤 2：构建本地模型安装器 ─────────────────
$installerBuildLog = Join-Path $LOG_DIR "local_model_installer_build_latest.log"
Write-Step "步骤 2/5  构建本地模型安装器（输出日志至 logs\local_model_installer_build_latest.log）"
$localInstallerExitCode = Invoke-CmdLogged -CommandLine ('{0} {1} --clean -y' -f (Format-CmdArg $VENV_PIP), (Format-CmdArg $LOCAL_INSTALLER_SPEC)) -LogPath $installerBuildLog
if ($localInstallerExitCode -ne 0) {
    Write-Fail "LocalModelInstaller 构建失败，查看详细日志：$installerBuildLog"
    Write-Host "(最后 30 行)" -ForegroundColor Yellow
    Get-Content $installerBuildLog -Tail 30
    exit 1
}
Write-OK "本地模型安装器构建完成 → dist\LocalModelInstaller.exe"

# ─── 步骤 3：组装便携包 ───────────────────────
Write-Step "步骤 3/5  组装便携包（dist\Koto_Portable\)"
$portableLog = Join-Path $LOG_DIR "deploy_portable.log"
$portableExitCode = Invoke-CmdLogged -CommandLine ('{0} {1}' -f (Format-CmdArg $PYTHON), (Format-CmdArg $DEPLOY_PY)) -LogPath $portableLog
if ($portableExitCode -ne 0) {
    Write-Fail "deploy_portable.py 失败，查看日志：$portableLog"
    Get-Content $portableLog -Tail 30
    exit 1
}
Write-OK "便携包已组装 → dist\Koto_Portable\"
Test-WorkspaceStaticAssets -StaticRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\web\static") -Label "便携包内前端产物"
Set-PackagedConfigDirectories -ConfigRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\config") -Label "便携包内默认配置"
Test-PackagedConfigDefaults -ConfigRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\config") -Label "便携包内默认配置"

# ─── 步骤 4：构建 Inno Setup 安装包（可选） ──────────────
Write-Step "步骤 4/5  构建安装包（Inno Setup，未安装则跳过）"
$resolveInno = Join-Path $REPO_ROOT "scripts\resolve_inno_setup.ps1"
$iscc = (& $resolveInno -Quiet) | Select-Object -First 1
if ($iscc) {
    $issFile = Join-Path $REPO_ROOT "koto_installer.iss"
    $isccLog = Join-Path $LOG_DIR "inno_setup_build.log"
    $isccExitCode = Invoke-CmdLogged -CommandLine ('{0} /DAppVersion={1} {2}' -f (Format-CmdArg $iscc), $Version, (Format-CmdArg $issFile)) -LogPath $isccLog
    if ($isccExitCode -ne 0) {
        Write-Fail "Inno Setup 构建失败，查看日志：$isccLog"
        Get-Content $isccLog -Tail 30
        exit 1
    }
    $setupName = "Koto_v${Version}_Setup.exe"
    Write-OK "安装包已生成 → dist\$setupName"
} else {
    Write-Host "  [--] 未检测到 Inno Setup 6，跳过安装包构建（可从 https://jrsoftware.org/isinfo.php 安装）" -ForegroundColor Yellow
}

# ─── 步骤 5：压缩为 zip ───────────────────────
Write-Step "步骤 5/5  压缩为 zip"
$zipName = "Koto_v${Version}_Windows.zip"
$zipPath = Join-Path $DIST_DIR $zipName
$portableDir = Join-Path $DIST_DIR "Koto_Portable"

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$portableDir\*" -DestinationPath $zipPath -CompressionLevel Optimal
Write-OK "zip 已生成 → dist\$zipName"

# ─── 完成 ─────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  打包完成！发布文件：dist\$zipName" -ForegroundColor Green
Write-Host "  用户使用方法：解压 → 填写 API Key → 双击 Start_Koto.bat" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
