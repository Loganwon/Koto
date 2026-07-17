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
    [switch]$AllowPrebuiltFrontend, # 仅用于无法安装 Node.js 的受限环境；不应作为正式发布路径
    [switch]$AllowNoInstaller,      # 仅生成便携包；不应作为完整 Windows 发布路径
    [switch]$AllowDirtyWorktree,    # 仅用于诊断构建；不得将产物作为正式发布版本
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
$MANIFEST_WRITER = Join-Path $REPO_ROOT "scripts\write_release_manifest.py"
$CYTHON_CLEANUP = Join-Path $REPO_ROOT "scripts\clean_inplace_cython_artifacts.py"

# ─── 颜色输出辅助 ─────────────────────────────
function Write-Step  { param([string]$msg) Write-Host "`n[$([char]0x25B6)] $msg" -ForegroundColor Cyan }
function Write-OK    { param([string]$msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail  { param([string]$msg) Write-Host "  [!!] $msg" -ForegroundColor Red }

function Get-GitWorktreeFingerprint {
    param([Parameter(Mandatory = $true)][string]$Root)

    $trackedDiffLines = @(& git -C $Root diff --no-ext-diff --binary HEAD --)
    if ($LASTEXITCODE -ne 0) {
        throw "无法读取 Git tracked diff，不能验证构建期间漂移。"
    }
    $untrackedPaths = @(& git -C $Root ls-files --others --exclude-standard | Sort-Object)
    if ($LASTEXITCODE -ne 0) {
        throw "无法读取 Git untracked 文件，不能验证构建期间漂移。"
    }

    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.Add("tracked-diff")
    $parts.Add([string]::Join("`n", $trackedDiffLines))
    $parts.Add("untracked-files")
    foreach ($relativePath in $untrackedPaths) {
        $fullPath = Join-Path $Root $relativePath
        $contentHash = if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
            (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash.ToLowerInvariant()
        } else {
            "missing"
        }
        $parts.Add("$relativePath`0$contentHash")
    }

    $payload = [System.Text.Encoding]::UTF8.GetBytes([string]::Join("`n", $parts))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($payload))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

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

function Test-WorkspaceStaticAssets {
    param(
        [Parameter(Mandatory = $true)][string]$StaticRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $required = @(
        (Join-Path $StaticRoot "js\build\workspace-bundle.js"),
        (Join-Path $StaticRoot "jszip.min.js"),
        (Join-Path $StaticRoot "univer-dist\assets\sheets-main.js"),
        (Join-Path $StaticRoot "univer-dist\assets\sheets-main.css")
    )

    foreach ($path in $required) {
        if (-not (Test-Path $path)) {
            throw "$Label 缺少关键静态资源: $path"
        }
    }

    $legacyIndex = Join-Path $StaticRoot "univer-dist\index.html"
    if (Test-Path $legacyIndex) {
        throw "$Label 包含已废弃的 Univer index.html: $legacyIndex"
    }

    Write-OK "$Label 关键静态资源齐全"
}

function Test-PackagedFrontendParity {
    param(
        [Parameter(Mandatory = $true)][string]$SourceWebRoot,
        [Parameter(Mandatory = $true)][string]$PackagedWebRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path $SourceWebRoot)) {
        throw "找不到源码 Web 目录: $SourceWebRoot"
    }
    if (-not (Test-Path $PackagedWebRoot)) {
        throw "$Label 缺少 Web 目录: $PackagedWebRoot"
    }

    # A release must be a byte-for-byte copy of the reviewed templates and
    # static assets.  Presence-only checks miss exactly the stale bundle case
    # where an old UI survives in a newly assembled installer.
    $frontendRoots = @('templates', 'static')
    $sourceFiles = @()
    foreach ($frontendRoot in $frontendRoots) {
        $sourceFrontendRoot = Join-Path $SourceWebRoot $frontendRoot
        if (-not (Test-Path $sourceFrontendRoot -PathType Container)) {
            throw "源码缺少前端目录: $sourceFrontendRoot"
        }
        $sourceFiles += @(Get-ChildItem -LiteralPath $sourceFrontendRoot -File -Recurse)
    }
    $sourceRoot = [System.IO.Path]::GetFullPath($SourceWebRoot).TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    $sourceRelativePaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($sourceFile in $sourceFiles) {
        $relativePath = $sourceFile.FullName.Substring($sourceRoot.Length)
        [void]$sourceRelativePaths.Add($relativePath)
        $packagedFile = Join-Path $PackagedWebRoot $relativePath
        if (-not (Test-Path $packagedFile -PathType Leaf)) {
            throw "$Label 缺少前端文件: $relativePath"
        }
        $sourceHash = (Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256).Hash
        $packagedHash = (Get-FileHash -LiteralPath $packagedFile -Algorithm SHA256).Hash
        if ($sourceHash -ne $packagedHash) {
            throw "$Label 前端文件与源码不一致: $relativePath"
        }
    }

    $packagedRoot = [System.IO.Path]::GetFullPath($PackagedWebRoot).TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    foreach ($frontendRoot in $frontendRoots) {
        $packagedFrontendRoot = Join-Path $PackagedWebRoot $frontendRoot
        if (-not (Test-Path $packagedFrontendRoot -PathType Container)) {
            throw "$Label 缺少前端目录: $packagedFrontendRoot"
        }
        foreach ($packagedFile in (Get-ChildItem -LiteralPath $packagedFrontendRoot -File -Recurse)) {
            $relativePath = $packagedFile.FullName.Substring($packagedRoot.Length)
            if (-not $sourceRelativePaths.Contains($relativePath)) {
                throw "$Label 包含源码中不存在的旧前端文件: $relativePath"
            }
        }
    }

    $removedFeatureMarkers = @(
        '学习包',
        '有声概览',
        'audio_overview',
        'notebook_guide',
        'openNotebookGuide',
        'openAudioOverview'
    )
    $legacyHits = @(Get-ChildItem -LiteralPath $PackagedWebRoot -File -Recurse |
        Select-String -Pattern $removedFeatureMarkers -SimpleMatch -List)
    if ($legacyHits.Count -gt 0) {
        $firstHit = $legacyHits[0]
        throw "$Label 仍包含已移除功能标记: $($firstHit.Path):$($firstHit.LineNumber)"
    }

    Write-OK "$Label 与源码前端完全一致，且不含已移除功能"
}

function Test-PackagedConfigDefaults {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $required = @(
        (Join-Path $ConfigRoot ".builtin_key"),
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

function Set-PackagedRuntimeConfigDefaults {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    # These files deliberately remain gitignored because they accumulate
    # personal runtime data.  A release must nevertheless start from a known
    # empty shape instead of relying on files that happen to exist on the
    # builder machine.
    $defaults = @(
        [pscustomobject]@{
            Name = "macro_suggestions.json"
            Content = @'
{
  "suggestions": [],
  "seen_fingerprints": []
}
'@
        },
        [pscustomobject]@{
            Name = "personality_matrix.json"
            Content = @'
{
  "cognitive": {
    "exploratory": 0.5,
    "executor": 0.5,
    "analytical": 0.5,
    "creative": 0.5
  },
  "expertise": {},
  "goals": [],
  "recent_themes": [],
  "values": {
    "efficiency": 0.5,
    "depth": 0.5,
    "formality": 0.5
  },
  "last_updated": null
}
'@
        }
    )

    foreach ($default in $defaults) {
        $path = Join-Path $ConfigRoot $default.Name
        if (-not (Test-Path $path)) {
            Set-Content -Path $path -Value $default.Content -Encoding UTF8
            Write-Host "  [--] 已补齐 $Label 运行时默认配置: $($default.Name)" -ForegroundColor Yellow
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

# The Cython step emits in-place extensions that the PyInstaller step consumes.
# A second build can otherwise finish first and delete those extensions during
# its cleanup, leaving the first build with dangling binary entries.  Keep the
# handle open for this PowerShell process; Windows releases it automatically on
# every exit path, so a stale lock file never blocks a later build.
$releaseBuildLockPath = Join-Path $LOG_DIR "release-build.lock"
try {
    $releaseBuildLock = [System.IO.File]::Open(
        $releaseBuildLockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-Fail "已有发布构建正在运行；为避免 Cython 产物互相清理，本次构建已取消。"
    exit 1
}
$lockMarker = [System.Text.Encoding]::UTF8.GetBytes("PID=$PID`nStarted=$(Get-Date -Format o)`n")
$releaseBuildLock.SetLength(0)
$releaseBuildLock.Write($lockMarker, 0, $lockMarker.Length)
$releaseBuildLock.Flush()
Write-OK "虚拟环境 OK"

# 正式发布必须对应一个可追溯的 Git 提交。否则 manifest 只能记录 HEAD，
# 却无法表达实际打包了哪些未提交内容，极易误发本地试验产物。
$gitStatus = @(& git -C $REPO_ROOT status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    Write-Fail "无法读取 Git 工作区状态；正式发布需要可追溯的 Git 仓库。"
    exit 1
}
if ($gitStatus.Count -gt 0) {
    if (-not $AllowDirtyWorktree) {
        Write-Fail "工作区存在未提交改动；请先审阅并提交，或仅为诊断构建显式传入 -AllowDirtyWorktree。"
        exit 1
    }
    Write-Host "  [--] 工作区存在 $($gitStatus.Count) 条未提交改动；本次仅为诊断构建，不得作为正式发布版本。" -ForegroundColor Yellow
}
$gitRevisionAtStart = (& git -C $REPO_ROOT rev-parse HEAD).Trim()
$gitFingerprintAtStart = Get-GitWorktreeFingerprint -Root $REPO_ROOT
$gitDirtyAtStart = if ($gitStatus.Count -gt 0) { "true" } else { "false" }

# ─── 版本号（单一来源：根目录 VERSION 文件）──────────
if ([string]::IsNullOrWhiteSpace($Version)) {
    $versionFile = Join-Path $REPO_ROOT "VERSION"
    if (Test-Path $versionFile) {
        $Version = (Get-Content $versionFile -Raw).Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = Get-Date -Format "yyyy.MM.dd" }
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._+\-]*$') {
    Write-Fail "版本号仅可包含字母、数字、点、下划线、加号和连字符，且必须以字母或数字开头。"
    exit 1
}
Write-OK "版本号: $Version"

# ─── 步骤 0：Cython 编译（保护核心模块 + _license key）────
if ($SkipCython) {
    Write-Step "步骤 0/5  跳过 Cython 编译（-SkipCython）"
} else {
    Write-Step "Cython 编译前清理源码覆盖产物"
    $cythonCleanupLog = Join-Path $LOG_DIR "cython_cleanup_preflight.log"
    $cythonCleanupExitCode = Invoke-ProcessLogged -FilePath $PYTHON -ArgumentList @($CYTHON_CLEANUP, '--apply') -WorkingDirectory $REPO_ROOT -LogPath $cythonCleanupLog
    if ($cythonCleanupExitCode -ne 0) {
        Write-Fail "无法清理旧 .pyd 覆盖产物；请先关闭源码模式的 Koto 进程。日志：$cythonCleanupLog"
        Get-Content $cythonCleanupLog -Tail 20
        exit 1
    }

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
Write-Step "步骤 0.5  前端资产构建（主界面 + DOCX 编辑器 + Univer Sheets）"
$webDir = Join-Path $REPO_ROOT "web"
$tiptapDir = Join-Path $REPO_ROOT "web\tiptap-editor"
$univDir = Join-Path $REPO_ROOT "web\univer-editor"
$staticRoot = Join-Path $REPO_ROOT "web\static"
$webFrontendInstallLog = Join-Path $LOG_DIR "web_frontend_npm_ci.log"
$webFrontendBuildLog = Join-Path $LOG_DIR "web_frontend_build.log"
$tiptapFrontendInstallLog = Join-Path $LOG_DIR "tiptap_frontend_npm_ci.log"
$tiptapFrontendBuildLog = Join-Path $LOG_DIR "tiptap_frontend_build.log"
$univerFrontendInstallLog = Join-Path $LOG_DIR "univer_frontend_npm_ci.log"
$univerFrontendBuildLog = Join-Path $LOG_DIR "univer_frontend_build.log"

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

    $frontendBuilds = @(
        [pscustomobject]@{ Label = "主 Web 前端"; Directory = $webDir; InstallLog = $webFrontendInstallLog; BuildLog = $webFrontendBuildLog },
        [pscustomobject]@{ Label = "DOCX TipTap 编辑器"; Directory = $tiptapDir; InstallLog = $tiptapFrontendInstallLog; BuildLog = $tiptapFrontendBuildLog },
        [pscustomobject]@{ Label = "Univer 文件助手前端"; Directory = $univDir; InstallLog = $univerFrontendInstallLog; BuildLog = $univerFrontendBuildLog }
    )
    foreach ($frontend in $frontendBuilds) {
        Write-Step "  [npm] 按锁文件安装 $($frontend.Label) 依赖..."
        $npmExitCode = Invoke-ProcessLogged -FilePath $npmExecutable -ArgumentList @('ci') -WorkingDirectory $frontend.Directory -LogPath $frontend.InstallLog
        if ($npmExitCode -ne 0) {
            Write-Fail "npm ci 失败，查看日志：$($frontend.InstallLog)"
            Get-Content $frontend.InstallLog -Tail 40
            exit 1
        }

        Write-Step "  [npm] 构建 $($frontend.Label) 资源..."
        $npmExitCode = Invoke-ProcessLogged -FilePath $npmExecutable -ArgumentList @('run', 'build') -WorkingDirectory $frontend.Directory -LogPath $frontend.BuildLog
        if ($npmExitCode -ne 0) {
            Write-Fail "npm run build 失败，查看日志：$($frontend.BuildLog)"
            Get-Content $frontend.BuildLog -Tail 60
            exit 1
        }
        Write-OK "$($frontend.Label) 构建完成"
    }
} else {
    if (-not $AllowPrebuiltFrontend) {
        Write-Fail "正式发布需要 Node.js/npm 从锁文件重建前端；如仅重打已有产物，请显式传入 -AllowPrebuiltFrontend。"
        exit 1
    }
    Write-Host "  [--] 已显式允许使用预构建前端资产；这不是完整发布路径。" -ForegroundColor Yellow
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
    Test-PackagedFrontendParity -SourceWebRoot $webDir -PackagedWebRoot (Join-Path $DIST_DIR "Koto\_internal\web") -Label "PyInstaller 包内前端"
    Set-PackagedConfigDirectories -ConfigRoot (Join-Path $DIST_DIR "Koto\_internal\config") -Label "PyInstaller 包内默认配置"
    Set-PackagedRuntimeConfigDefaults -ConfigRoot (Join-Path $DIST_DIR "Koto\_internal\config") -Label "PyInstaller 包内默认配置"
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
Test-PackagedFrontendParity -SourceWebRoot $webDir -PackagedWebRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\web") -Label "便携包内前端"
Set-PackagedConfigDirectories -ConfigRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\config") -Label "便携包内默认配置"
Set-PackagedRuntimeConfigDefaults -ConfigRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\config") -Label "便携包内默认配置"
Test-PackagedConfigDefaults -ConfigRoot (Join-Path $DIST_DIR "Koto_Portable\_internal\config") -Label "便携包内默认配置"

# ─── 步骤 4：构建 Inno Setup 安装包 ─────────────────────
Write-Step "步骤 4/5  构建安装包（Inno Setup）"
$resolveInno = Join-Path $REPO_ROOT "scripts\resolve_inno_setup.ps1"
$iscc = (& $resolveInno -Quiet) | Select-Object -First 1
$setupName = "Koto_v${Version}_Setup.exe"
$setupPath = Join-Path $DIST_DIR $setupName
if ($iscc) {
    $issFile = Join-Path $REPO_ROOT "koto_installer.iss"
    $isccLog = Join-Path $LOG_DIR "inno_setup_build.log"
    $isccExitCode = Invoke-CmdLogged -CommandLine ('{0} /DAppVersion={1} {2}' -f (Format-CmdArg $iscc), $Version, (Format-CmdArg $issFile)) -LogPath $isccLog
    if ($isccExitCode -ne 0) {
        Write-Fail "Inno Setup 构建失败，查看日志：$isccLog"
        Get-Content $isccLog -Tail 30
        exit 1
    }
    Write-OK "安装包已生成 → dist\$setupName"
} else {
    if (-not $AllowNoInstaller) {
        Write-Fail "未检测到 Inno Setup 6；完整 Windows 发布必须生成安装包。仅生成便携包时请显式传入 -AllowNoInstaller。"
        exit 1
    }
    Write-Host "  [--] 已显式允许缺少安装包；只生成便携包。" -ForegroundColor Yellow
}

# ─── 步骤 5：压缩为 zip ───────────────────────
Write-Step "步骤 5/5  压缩为 zip"
$zipName = "Koto_v${Version}_Windows.zip"
$zipPath = Join-Path $DIST_DIR $zipName
$portableDir = Join-Path $DIST_DIR "Koto_Portable"

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$portableDir\*" -DestinationPath $zipPath -CompressionLevel Optimal
Write-OK "zip 已生成 → dist\$zipName"

# ─── 步骤 6：生成发布清单与校验和 ──────────────────────
Write-Step "步骤 6/6  生成发布清单与 SHA-256 校验和"
$gitRevisionAtEnd = (& git -C $REPO_ROOT rev-parse HEAD).Trim()
$gitFingerprintAtEnd = Get-GitWorktreeFingerprint -Root $REPO_ROOT
$worktreeChangedDuringBuild = (
    $gitRevisionAtStart -ne $gitRevisionAtEnd -or
    $gitFingerprintAtStart -ne $gitFingerprintAtEnd
)
if ($worktreeChangedDuringBuild -and -not $AllowDirtyWorktree) {
    Write-Fail "构建期间 Git revision 或工作区内容发生变化；已拒绝生成正式发布清单，请从冻结提交重新构建。"
    exit 1
}
$worktreeChangedState = if ($worktreeChangedDuringBuild) { "true" } else { "false" }
if ($worktreeChangedDuringBuild) {
    Write-Host "  [--] 构建期间工作区发生漂移；manifest 将标记为诊断产物，不得发布。" -ForegroundColor Yellow
}
$manifestPath = Join-Path $DIST_DIR "Koto_v${Version}_release-manifest.json"
$checksumPath = Join-Path $DIST_DIR "Koto_v${Version}_SHA256SUMS.txt"
$artifacts = @($zipPath)
if (Test-Path $setupPath) { $artifacts += $setupPath }
$manifestArgs = @(
    $MANIFEST_WRITER,
    '--version', $Version,
    '--output', $manifestPath,
    '--hash-output', $checksumPath,
    '--git-revision', $gitRevisionAtStart,
    '--git-dirty', $gitDirtyAtStart,
    '--worktree-changed-during-build', $worktreeChangedState
) + $artifacts
$manifestExitCode = Invoke-ProcessLogged -FilePath $PYTHON -ArgumentList $manifestArgs -WorkingDirectory $REPO_ROOT -LogPath (Join-Path $LOG_DIR 'release_manifest.log')
if ($manifestExitCode -ne 0) {
    Write-Fail "生成发布清单失败，查看日志：logs\release_manifest.log"
    exit 1
}
Write-OK "发布清单 → dist\$(Split-Path $manifestPath -Leaf)"
Write-OK "SHA-256 → dist\$(Split-Path $checksumPath -Leaf)"

if (-not $SkipCython) {
    Write-Step "发布收尾：清理源码覆盖产物"
    $cythonCleanupLog = Join-Path $LOG_DIR "cython_cleanup_postbuild.log"
    $cythonCleanupExitCode = Invoke-ProcessLogged -FilePath $PYTHON -ArgumentList @($CYTHON_CLEANUP, '--apply') -WorkingDirectory $REPO_ROOT -LogPath $cythonCleanupLog
    if ($cythonCleanupExitCode -ne 0) {
        Write-Host "  [--] 发布包已完成，但源码目录仍有被锁定的 .pyd；关闭源码实例后运行清理工具。日志：$cythonCleanupLog" -ForegroundColor Yellow
    } else {
        Write-OK "源码覆盖产物已清理，开发启动将使用当前 Python 源码"
    }
}

# ─── 完成 ─────────────────────────────────────
Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  打包完成！发布文件：dist\$zipName" -ForegroundColor Green
if (Test-Path $setupPath) { Write-Host "  安装包：dist\$setupName" -ForegroundColor Green }
Write-Host "  校验文件：dist\$(Split-Path $checksumPath -Leaf)" -ForegroundColor Green
Write-Host "  用户使用方法：解压 → 填写 API Key → 双击 Start_Koto.bat" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
