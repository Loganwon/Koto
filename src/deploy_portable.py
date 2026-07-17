# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""组装可分发的 Koto Windows 便携包。"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import time
from pathlib import Path

# __file__ 在 src/ 下，所以需要 .parent.parent 回到项目根目录
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent if _HERE.name == "src" else _HERE
APP_BUILD_DIR = ROOT / "dist" / "Koto"
OUTPUT_DIR = ROOT / "dist" / "Koto_Portable"
RELEASE_ROOT_ENTRIES = (
    "Koto.exe",
    "_internal",
)
WEBVIEW2_INSTALLER_NAME = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
WEBVIEW2_METADATA_NAME = "webview2-runtime.json"
WEBVIEW2_PREREQUISITE_DIR = ROOT / "build" / "prerequisites"
REQUIRED_CONFIG_DIRS = (
    "context",
    "divination_data",
    "skills",
    "skill_packs",
    "tools",
    "workflows",
)

LOCAL_INSTALLER_CANDIDATES = [
    ROOT / "dist" / "LocalModelInstaller.exe",
    ROOT / "dist" / "LocalModelInstaller" / "LocalModelInstaller.exe",
    ROOT / "dist" / "local_model_installer" / "LocalModelInstaller.exe",
]


PORTABLE_README = """Koto Windows 便携版
====================

使用步骤：
1. 双击 Start_Koto.bat 或 Koto.exe。
2. 首次启动时选择一种 AI 方式：填写 DeepSeek API Key，或下载本地模型。
3. 选择本地模型时，Koto 会引导安装 Ollama 并下载推荐模型（约 1–8 GB）。
4. 后续直接双击 Start_Koto.bat 即可使用；Install_Local_Model.bat 可用于以后更换模型。

目录说明：
- Koto.exe: 主程序
- Start_Koto.bat: 推荐启动入口
- Stop_Koto.bat: 关闭 Koto
- MicrosoftEdgeWebView2RuntimeInstallerX64.exe: 微软官方离线界面运行时（缺失时自动安装）
- Install_WebView2_Runtime.bat: 手动修复界面运行时
- Install_Local_Model.bat: 本地模型安装入口
- LocalModelInstaller.exe: 独立本地模型安装器

分发建议：
1. 将整个 Koto_Portable 文件夹压缩为 zip 后发送。
2. 收件人解压到任意本地目录即可使用。
3. 不建议直接在压缩包内运行。
"""


def find_local_installer() -> Path | None:
    for candidate in LOCAL_INSTALLER_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def find_webview2_installer() -> Path | None:
    candidate = WEBVIEW2_PREREQUISITE_DIR / WEBVIEW2_INSTALLER_NAME
    return candidate if candidate.is_file() else None


def _handle_remove_error(func, path, exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    func(path)


def ensure_clean_output(output_dir: Path) -> None:
    if output_dir.exists():
        last_error = None
        for _ in range(3):
            try:
                shutil.rmtree(output_dir, onerror=_handle_remove_error)
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.5)
        if output_dir.exists():
            raise last_error or OSError(f"无法清理输出目录: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def ensure_required_config_dirs(config_root: Path) -> None:
    for dir_name in REQUIRED_CONFIG_DIRS:
        (config_root / dir_name).mkdir(parents=True, exist_ok=True)


def create_launchers(
    output_dir: Path,
    include_installer: bool,
    include_webview2_installer: bool,
) -> None:
    write_text(
        output_dir / "Start_Koto.bat",
        "@echo off\n"
        "setlocal\n"
        'cd /d "%~dp0"\n'
        'start "" "%~dp0Koto.exe"\n'
        "endlocal\n",
    )

    write_text(
        output_dir / "Stop_Koto.bat",
        "@echo off\n"
        "setlocal EnableDelayedExpansion\n"
        'cd /d "%~dp0"\n'
        'set "LOCK_FILE=%~dp0.koto.lock"\n'
        'if exist "%LOCK_FILE%" (\n'
        '  set /p LOCKED_PID=<"%LOCK_FILE%"\n'
        '  if defined LOCKED_PID if not "!LOCKED_PID!"=="starting" taskkill /F /PID !LOCKED_PID! >nul 2>&1\n'
        '  del /F "%LOCK_FILE%" >nul 2>&1\n'
        ")\n"
        "taskkill /F /IM Koto.exe >nul 2>&1\n"
        "endlocal\n",
    )

    if include_installer:
        install_content = (
            "@echo off\n"
            "setlocal\n"
            'cd /d "%~dp0"\n'
            'start "" "%~dp0LocalModelInstaller.exe"\n'
            "endlocal\n"
        )
    else:
        install_content = (
            "@echo off\n"
            "echo [ERROR] 当前便携包未包含 LocalModelInstaller.exe\n"
            "echo 请先在开发机执行 pyinstaller local_model_installer.spec --clean -y\n"
            "pause\n"
        )
    write_text(output_dir / "Install_Local_Model.bat", install_content)

    if include_webview2_installer:
        webview2_content = (
            "@echo off\n"
            "setlocal\n"
            'cd /d "%~dp0"\n'
            f'"%~dp0{WEBVIEW2_INSTALLER_NAME}" /silent /install\n'
            "if errorlevel 1 (\n"
            "  echo [ERROR] WebView2 Runtime installation failed.\n"
            "  pause\n"
            ")\n"
            "endlocal\n"
        )
    else:
        webview2_content = (
            "@echo off\n"
            "echo [ERROR] This development bundle does not include the WebView2 Runtime installer.\n"
            "pause\n"
        )
    write_text(output_dir / "Install_WebView2_Runtime.bat", webview2_content)


def build_portable_bundle(
    output_dir: Path,
    strict_installer: bool,
    strict_webview2: bool,
) -> None:
    if not APP_BUILD_DIR.exists():
        raise FileNotFoundError(f"未找到主程序构建目录: {APP_BUILD_DIR}")

    installer_path = find_local_installer()
    if strict_installer and installer_path is None:
        raise FileNotFoundError(
            "未找到 LocalModelInstaller.exe，请先构建本地模型安装器"
        )
    webview2_installer = find_webview2_installer()
    if strict_webview2 and webview2_installer is None:
        raise FileNotFoundError(
            "未找到微软 WebView2 离线运行时；请先运行 "
            "scripts/prepare_webview2_runtime.ps1"
        )

    ensure_clean_output(output_dir)

    for entry_name in RELEASE_ROOT_ENTRIES:
        source_path = APP_BUILD_DIR / entry_name
        if not source_path.exists():
            raise FileNotFoundError(f"发行目录缺少必需项: {source_path}")
        target_path = output_dir / entry_name
        if source_path.is_dir():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, target_path)

    ensure_required_config_dirs(output_dir / "_internal" / "config")

    if installer_path is not None:
        shutil.copy2(installer_path, output_dir / "LocalModelInstaller.exe")

    if webview2_installer is not None:
        shutil.copy2(webview2_installer, output_dir / WEBVIEW2_INSTALLER_NAME)
        metadata = WEBVIEW2_PREREQUISITE_DIR / WEBVIEW2_METADATA_NAME
        if metadata.is_file():
            shutil.copy2(metadata, output_dir / WEBVIEW2_METADATA_NAME)

    create_launchers(
        output_dir,
        installer_path is not None,
        webview2_installer is not None,
    )
    write_text(output_dir / "README_便携版.txt", PORTABLE_README)

    docs_src = ROOT / "docs" / "PORTABLE_RELEASE_GUIDE.md"
    if docs_src.exists():
        shutil.copy2(docs_src, output_dir / "PORTABLE_RELEASE_GUIDE.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="组装 Koto Windows 便携分发目录")
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR),
        help="输出目录，默认 dist/Koto_Portable",
    )
    parser.add_argument(
        "--allow-missing-installer",
        action="store_true",
        help="允许在缺少 LocalModelInstaller.exe 时继续组装",
    )
    parser.add_argument(
        "--allow-missing-webview2-runtime",
        action="store_true",
        help="仅开发诊断：允许缺少微软 WebView2 离线运行时",
    )
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    build_portable_bundle(
        output_dir,
        strict_installer=not args.allow_missing_installer,
        strict_webview2=not args.allow_missing_webview2_runtime,
    )

    print(f"✅ 便携包已生成: {output_dir}")
    print("建议将该目录压缩为 zip 后发送给 Windows 用户。")


if __name__ == "__main__":
    main()
