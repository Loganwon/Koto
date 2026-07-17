#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
koto_setup.py — Koto 启动入口（带首次 AI 方式设置）

打包后产生的 EXE 入口：
  1. 首次运行 → 用户选择云端 API 或本地模型
  2. 后续运行 → 直接启动 Koto 桌面程序
"""

import os
import runpy
import subprocess
import sys
from pathlib import Path

try:
    from src.runtime_bootstrap import (
        configure_process_environment,
        resolve_runtime_roots,
    )
except ImportError:
    from runtime_bootstrap import configure_process_environment, resolve_runtime_roots

# ── 路径配置 ──────────────────────────────────────────
ROOTS = resolve_runtime_roots(__file__)
APP_ROOT = ROOTS.app_root
BUNDLE_DIR = ROOTS.bundle_dir

if getattr(sys, "frozen", False):
    # PyInstaller 环境
    # Fix pythonnet runtime path for pywebview's EdgeChromium backend in frozen environment
    # This must be set before any import of webview or clr
    _internal_py = APP_ROOT / "internal" / "py"
    if _internal_py.exists():
        os.environ.setdefault(
            "PYTHONNET_PYDLL",
            str(
                _internal_py
                / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
            ),
        )
    os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")


configure_process_environment(
    ROOTS,
    prepend_paths=(APP_ROOT, BUNDLE_DIR),
    required_dirs=("logs", "chats", "config", "workspace"),
)


def _sync_bundled_config_defaults():
    """将打包内置的默认配置同步到运行目录，仅补缺不覆盖用户文件。"""
    bundled_config = BUNDLE_DIR / "config"
    runtime_config = APP_ROOT / "config"
    if not bundled_config.exists() or bundled_config == runtime_config:
        return

    import shutil

    for src_dir, _, filenames in os.walk(bundled_config):
        src_path = Path(src_dir)
        rel_path = src_path.relative_to(bundled_config)
        dst_path = runtime_config / rel_path
        dst_path.mkdir(parents=True, exist_ok=True)

        for filename in filenames:
            src_file = src_path / filename
            dst_file = dst_path / filename
            if dst_file.exists():
                continue
            try:
                shutil.copy2(src_file, dst_file)
            except Exception:
                pass


_sync_bundled_config_defaults()

# 图标资源目录：打包模式下在 _MEIPASS/assets/，源码模式下在 src/assets/
ASSETS_DIR = (
    BUNDLE_DIR if getattr(sys, "frozen", False) else APP_ROOT / "src"
) / "assets"


def _read_user_cloud_provider(default: str = "deepseek") -> str:
    try:
        from app.core.config.settings_store import load_settings_document

        data = load_settings_document(APP_ROOT / "config" / "user_settings.json")
        provider = str(data.get("ai", {}).get("cloud_provider") or "").strip().lower()
        if provider == "deepseek":
            return provider
    except Exception:
        pass
    env_provider = (
        os.getenv("KOTO_CLOUD_PROVIDER") or os.getenv("KOTO_LLM_PROVIDER") or default
    )
    return "deepseek" if str(env_provider).strip().lower() == "deepseek" else "deepseek"


# ── API 密钥配置向导 ───────────────────────────────────
def _show_api_setup_wizard(initial_status: str = "") -> dict:
    """显示云端 API 密钥配置弹窗，返回用户选择的供应商与密钥。"""
    import tkinter as tk
    from tkinter import font as tkfont

    result = {
        "provider": _read_user_cloud_provider(),
        "key": None,
        "base": "",
        "code": "",
        "cancelled": False,
    }

    root = tk.Tk()
    root.title("Koto 初始化配置")
    root.resizable(True, True)

    # ── 颜色常量 ──
    BG = "#05080f"
    BG2 = "#0b111d"
    BG3 = "#111a2a"
    ACCENT = "#63c6ff"
    TEXT = "#e8eefc"
    TEXT2 = "#9fb3d1"
    BORDER = "#1e2d45"
    SUCCESS = "#76f7d4"
    DANGER = "#ef6b6b"

    root.configure(bg=BG)

    # ── 让窗口居中 ──
    W, H = 480, 820
    root.geometry(f"{W}x{H}")
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W)//2}+{(sh - H)//2}")

    # 固定在最顶层
    root.lift()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False))

    # ── 尝试设置图标 ──
    try:
        ico = ASSETS_DIR / "koto_icon.ico"
        if ico.exists():
            root.iconbitmap(str(ico))
    except Exception:
        pass

    # ── Fonts ──
    f_title = tkfont.Font(family="Microsoft YaHei UI", size=16, weight="bold")
    f_sub = tkfont.Font(family="Microsoft YaHei UI", size=10)
    f_label = tkfont.Font(family="Microsoft YaHei UI", size=9, weight="bold")
    f_input = tkfont.Font(family="Consolas", size=11)
    f_hint = tkfont.Font(family="Microsoft YaHei UI", size=8)
    f_btn = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
    f_step = tkfont.Font(family="Microsoft YaHei UI", size=8)

    # ── 顶部品牌区 ──
    top = tk.Frame(root, bg=BG2, height=90)
    top.pack(fill="x")
    top.pack_propagate(False)

    tk.Label(top, text="Koto  言", font=f_title, bg=BG2, fg=ACCENT).pack(pady=(18, 2))
    tk.Label(top, text="AI 助手 · 首次启动配置", font=f_sub, bg=BG2, fg=TEXT2).pack()

    # ── 分隔线 ──
    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

    # ── 主内容区 ──
    body = tk.Frame(root, bg=BG, padx=28, pady=20)
    body.pack(fill="both", expand=True)

    provider_var = tk.StringVar(value=result["provider"])

    # ── 步骤说明 ──
    steps_frame = tk.Frame(body, bg=BG3, padx=12, pady=10)
    steps_frame.pack(fill="x", pady=(0, 16))
    steps_title = tk.Label(
        steps_frame,
        text="如何获取 DeepSeek API 密钥：",
        font=f_step,
        bg=BG3,
        fg=TEXT2,
        anchor="w",
    )
    steps_title.pack(fill="x")
    step_labels = []
    deepseek_steps = [
        "① 访问  https://platform.deepseek.com/api_keys",
        "② 登录 DeepSeek 账号",
        "③ 创建新的 API Key",
        "④ 复制密钥粘贴到下方输入框",
    ]
    for s in deepseek_steps:
        lbl = tk.Label(steps_frame, text=s, font=f_step, bg=BG3, fg=TEXT2, anchor="w")
        lbl.pack(fill="x", pady=1)
        step_labels.append(lbl)

    # ── 云端供应商 ──
    tk.Label(body, text="云端供应商", font=f_label, bg=BG, fg=ACCENT, anchor="w").pack(
        fill="x", pady=(0, 6)
    )
    provider_row = tk.Frame(body, bg=BG)
    provider_row.pack(fill="x", pady=(0, 12))

    def _radio(label: str, value: str):
        tk.Radiobutton(
            provider_row,
            text=label,
            variable=provider_var,
            value=value,
            command=lambda: sync_provider_ui(provider_var.get()),
            font=f_hint,
            bg=BG,
            fg=TEXT2,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=BG3,
            relief="flat",
            bd=0,
        ).pack(side="left", padx=(0, 18))

    _radio("DeepSeek", "deepseek")

    # ── API Key 输入 ──
    key_label = tk.Label(
        body, text="DeepSeek API 密钥  *", font=f_label, bg=BG, fg=ACCENT, anchor="w"
    )
    key_label.pack(fill="x", pady=(0, 4))

    key_var = tk.StringVar()
    key_frame = tk.Frame(body, bg=BORDER, padx=1, pady=1)
    key_frame.pack(fill="x", pady=(0, 4))
    key_inner = tk.Frame(key_frame, bg=BG2)
    key_inner.pack(fill="x")
    key_entry = tk.Entry(
        key_inner,
        textvariable=key_var,
        font=f_input,
        bg=BG2,
        fg=TEXT,
        insertbackground=ACCENT,
        relief="flat",
        show="•",
        bd=8,
    )
    key_entry.pack(fill="x")

    # 显示/隐藏密钥
    show_var = tk.BooleanVar(value=False)

    def toggle_show():
        key_entry.config(show="" if show_var.get() else "•")

    tk.Checkbutton(
        body,
        text="显示密钥",
        variable=show_var,
        command=toggle_show,
        font=f_hint,
        bg=BG,
        fg=TEXT2,
        activebackground=BG,
        activeforeground=TEXT,
        selectcolor=BG3,
        relief="flat",
        bd=0,
    ).pack(anchor="w", pady=(0, 12))

    # ── 自定义 API 端点（可选）──
    tk.Label(
        body,
        text="自定义 API 端点（可选，中转代理用）",
        font=f_label,
        bg=BG,
        fg=TEXT2,
        anchor="w",
    ).pack(fill="x", pady=(0, 4))
    base_var = tk.StringVar()
    base_frame = tk.Frame(body, bg=BORDER, padx=1, pady=1)
    base_frame.pack(fill="x", pady=(0, 4))
    base_inner = tk.Frame(base_frame, bg=BG2)
    base_inner.pack(fill="x")
    tk.Entry(
        base_inner,
        textvariable=base_var,
        font=f_input,
        bg=BG2,
        fg=TEXT,
        insertbackground=ACCENT,
        relief="flat",
        bd=8,
    ).pack(fill="x")
    base_hint_label = tk.Label(
        body,
        text="例: https://your-proxy.com/v1beta",
        font=f_hint,
        bg=BG,
        fg=TEXT2,
        anchor="w",
    )
    base_hint_label.pack(fill="x", pady=(0, 14))

    # ── 激活码分隔线 ──
    sep_row = tk.Frame(body, bg=BG)
    sep_row.pack(fill="x", pady=(4, 10))
    tk.Frame(sep_row, bg=BORDER, height=1).pack(side="left", fill="x", expand=True)
    tk.Label(sep_row, text="  或使用激活码  ", font=f_hint, bg=BG, fg=TEXT2).pack(
        side="left"
    )
    tk.Frame(sep_row, bg=BORDER, height=1).pack(side="left", fill="x", expand=True)

    # ── 激活码输入 ──
    tk.Label(body, text="激活码", font=f_label, bg=BG, fg=TEXT2, anchor="w").pack(
        fill="x", pady=(0, 4)
    )
    code_var = tk.StringVar()
    code_frame = tk.Frame(body, bg=BORDER, padx=1, pady=1)
    code_frame.pack(fill="x", pady=(0, 4))
    code_inner = tk.Frame(code_frame, bg=BG2)
    code_inner.pack(fill="x")
    tk.Entry(
        code_inner,
        textvariable=code_var,
        font=f_input,
        bg=BG2,
        fg=TEXT,
        insertbackground=ACCENT,
        relief="flat",
        bd=8,
    ).pack(fill="x")
    code_hint_label = tk.Label(
        body,
        text="💬 没有 API Key 或激活码？加微信 18913921188 申请",
        font=f_hint,
        bg=BG,
        fg=TEXT2,
        anchor="w",
    )
    code_hint_label.pack(fill="x", pady=(2, 12))

    def sync_provider_ui(provider: str):
        provider_var.set("deepseek")
        steps_title.config(text="如何获取 DeepSeek API 密钥：")
        for idx, lbl in enumerate(step_labels):
            lbl.config(text=deepseek_steps[idx])
        key_label.config(text="DeepSeek API 密钥  *")
        base_hint_label.config(text="默认: https://api.deepseek.com")
        code_hint_label.config(text="激活码已停用，请填写 DeepSeek API Key")

    sync_provider_ui(provider_var.get())

    # ── 状态提示 ──
    status_var = tk.StringVar(value="")
    status_lbl = tk.Label(
        body,
        textvariable=status_var,
        font=f_hint,
        bg=BG,
        fg=DANGER,
        anchor="w",
        wraplength=420,
    )
    status_lbl.pack(fill="x", pady=(0, 8))

    # 如果携带了初始状态（例如：密钥失效提示），立即显示
    if initial_status:
        status_var.set(initial_status)
        status_lbl.config(fg=DANGER)

    # ── 按钮行 ──
    btn_row = tk.Frame(body, bg=BG)
    btn_row.pack(fill="x", side="bottom")

    def on_cancel():
        result["cancelled"] = True
        root.destroy()

    def on_confirm():
        raw_key = key_var.get().strip()
        code = code_var.get().strip()
        provider = provider_var.get()
        if not raw_key:
            status_var.set("❌ 请输入 DeepSeek API 密钥")
            status_lbl.config(fg=DANGER)
            key_entry.focus_set()
            return
        _save()

    def _save():
        raw_key = key_var.get().strip()
        base = base_var.get().strip()
        code = code_var.get().strip()
        result["provider"] = provider_var.get()
        result["key"] = raw_key or None
        result["base"] = base
        result["code"] = code
        status_var.set("✅ 保存成功，正在启动…")
        status_lbl.config(fg=SUCCESS)
        root.after(600, root.destroy)

    def on_test():
        raw_key = key_var.get().strip()
        if not raw_key:
            status_var.set("❌ 请先输入 API 密钥")
            status_lbl.config(fg=DANGER)
            return
        base = base_var.get().strip()
        status_var.set("⏳ 正在验证密钥…")
        status_lbl.config(fg=TEXT2)
        root.update()
        ok, msg = _validate_api_key(raw_key, base, provider=provider_var.get())
        if ok:
            status_var.set("✅ 密钥有效！可以保存")
            status_lbl.config(fg=SUCCESS)
        else:
            status_var.set(msg or "❌ 密钥验证失败")
            status_lbl.config(fg=DANGER)

    cancel_btn = tk.Button(
        btn_row,
        text="跳过",
        font=f_btn,
        bg=BG3,
        fg=TEXT2,
        activebackground=BORDER,
        relief="flat",
        bd=0,
        padx=18,
        pady=10,
        cursor="hand2",
        command=on_cancel,
    )
    cancel_btn.pack(side="left")

    test_btn = tk.Button(
        btn_row,
        text="测试密钥",
        font=f_btn,
        bg=BG3,
        fg=TEXT2,
        activebackground=BORDER,
        relief="flat",
        bd=0,
        padx=14,
        pady=10,
        cursor="hand2",
        command=on_test,
    )
    test_btn.pack(side="left", padx=(8, 0))

    confirm_btn = tk.Button(
        btn_row,
        text="保存并启动  →",
        font=f_btn,
        bg=ACCENT,
        fg="#05080f",
        activebackground="#4db8f0",
        relief="flat",
        bd=0,
        padx=18,
        pady=10,
        cursor="hand2",
        command=on_confirm,
    )
    confirm_btn.pack(side="right")

    # Enter 键确认
    root.bind("<Return>", lambda e: on_confirm())
    root.bind("<Escape>", lambda e: on_cancel())

    key_entry.focus_set()
    root.mainloop()
    return result


def _write_deepseek_config(api_key: str, api_base: str = ""):
    """将用户填写的 DeepSeek API 信息写入 deepseek_config.env"""
    config_dir = APP_ROOT / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "deepseek_config.env"
    base = api_base.strip() or "https://api.deepseek.com"

    lines = [
        "# Koto DeepSeek 配置文件（由启动向导自动生成）\n",
        f"DEEPSEEK_API_KEY={api_key}\n",
        f"DEEPSEEK_BASE_URL={base}\n",
    ]
    config_path.write_text("".join(lines), encoding="utf-8")


def _write_cloud_provider_setting(provider: str):
    """同步云端供应商到 user_settings.json，便于 Web 设置页与运行时识别。"""
    provider = "deepseek"
    settings_path = APP_ROOT / "config" / "user_settings.json"
    try:
        from app.core.config.settings_store import atomic_update_settings

        atomic_update_settings(
            settings_path,
            {
                "ai": {
                    "cloud_provider": provider,
                    "deepseek_model": "deepseek-chat",
                },
                "model_mode": "cloud",
            },
        )
    except Exception:
        pass


def _write_cloud_config(provider: str, api_key: str, api_base: str = ""):
    _write_deepseek_config(api_key, api_base)
    _write_cloud_provider_setting("deepseek")


def _api_key_configured(provider: str | None = None) -> bool:
    """检查是否已有有效的云端 API 密钥配置"""
    provider = provider or _read_user_cloud_provider()
    cfg = APP_ROOT / "config" / "deepseek_config.env"
    if not cfg.exists():
        return False
    text = cfg.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        key_prefixes = ("DEEPSEEK_API_KEY=", "DEEPSEEK_KEY=", "DS_API_KEY=", "DS_KEY=")
        if line.startswith(key_prefixes):
            val = line.split("=", 1)[1].strip()
            if val and val not in ("your_api_key_here", "", "None"):
                return True
    return False


def _local_model_configured() -> bool:
    """Return whether first-run setup completed with the local-model path."""
    import json

    config_dir = APP_ROOT / "config"
    try:
        flag = json.loads((config_dir / "model_setup_done.json").read_text(encoding="utf-8"))
        if isinstance(flag, dict) and flag.get("done") and flag.get("mode") == "local":
            return bool(str(flag.get("model") or "").strip())
    except Exception:
        pass
    try:
        from app.core.config.settings_store import load_settings_document

        settings = load_settings_document(config_dir / "user_settings.json")
        return (
            isinstance(settings, dict)
            and settings.get("model_mode") == "local"
            and bool(str(settings.get("local_model") or "").strip())
        )
    except Exception:
        return False


def _run_unified_setup() -> bool:
    """Run the bundled chooser and require cloud or local configuration."""
    installer = APP_ROOT / "LocalModelInstaller.exe"
    source_installer = APP_ROOT / "src" / "local_model_installer.py"
    try:
        if installer.exists():
            subprocess.run([str(installer)], cwd=str(APP_ROOT), check=False)
        elif source_installer.exists():
            subprocess.run([sys.executable, str(source_installer)], cwd=str(APP_ROOT), check=False)
        else:
            return False
    except Exception:
        return False
    return _api_key_configured() or _local_model_configured()


def _read_config_values(provider: str | None = None) -> tuple:
    """从供应商配置文件读取 (api_key, api_base)"""
    provider = provider or _read_user_cloud_provider()
    cfg = APP_ROOT / "config" / "deepseek_config.env"
    key, base = "", ""
    if not cfg.exists():
        return key, base
    for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if (
            line.startswith(
                ("DEEPSEEK_API_KEY=", "DEEPSEEK_KEY=", "DS_API_KEY=", "DS_KEY=")
            )
            and not key
        ):
            key = line.split("=", 1)[1].strip()
        elif line.startswith(("DEEPSEEK_BASE_URL=", "DEEPSEEK_API_BASE=")) and not base:
            base = line.split("=", 1)[1].strip()
    return key, base


def _validate_api_key(key: str, base: str = "", provider: str = "deepseek") -> tuple:
    """向云端服务器发送轻量请求验证密钥，返回 (ok: bool, msg: str)。
    超时 8 秒，网络异常时返回 (False, ⚠️ 提示) 而不是 (False, ❌ 无效)。"""
    try:
        import urllib.error
        import urllib.request

        base_url = (base.strip() or "https://api.deepseek.com").rstrip("/")
        urls = [f"{base_url}/models"]
        if not base_url.endswith("/v1"):
            urls.append(f"{base_url}/v1/models")
        last_error = None
        for url in urls:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=8) as r:
                    if r.status == 200:
                        return (True, "")
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code != 404:
                    raise
        if last_error:
            raise last_error
        return (False, "❌ DeepSeek 密钥验证失败")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return (False, "❌ 密钥无效（API_KEY_INVALID）")
        if e.code in (401, 403):
            return (False, "❌ 密钥被拒绝（权限不足）")
        return (False, f"❌ HTTP 错误 {e.code}")
    except Exception as e:
        msg = str(e)
        return (False, f"⚠️ 网络异常，无法验证（{msg[:60]}）")


def _run_setup_if_needed() -> bool:
    """Require a usable cloud key or a configured local model before launch."""
    # 支持命令行强制重新配置:  Koto.exe --setup
    force = "--setup" in sys.argv or "--reconfigure" in sys.argv

    # 如果内置密钥文件存在且尚未配置，跳过桌面向导（由 Web 界面处理激活码）
    builtin_key_file = APP_ROOT / "config" / ".builtin_key"
    if not force and builtin_key_file.exists():
        return True

    wizard_status = ""  # 传给向导的初始提示（密钥失效时填充）
    provider = _read_user_cloud_provider()

    if not force:
        if _local_model_configured():
            return True
        if not _api_key_configured(provider):
            return _run_unified_setup()
        else:
            # 密钥存在 → 静默验证（网络正常时 ~1-3s）
            key, base = _read_config_values(provider)
            if not key:
                pass  # 无有效 key → 弹向导
            else:
                ok, err_msg = _validate_api_key(key, base, provider=provider)
                if ok:
                    return True  # 验证通过，正常启动
                # 网络异常（⚠️前缀）→ 不强制弹向导，允许继续启动
                if err_msg.startswith("⚠️"):
                    return True
                # 密钥明确无效（❌前缀）→ 弹向导并带提示
                wizard_status = f"{err_msg} — 请重新填写密钥"

    # Unified chooser is present in every supported installer/portable build.
    # It has no "continue without configuration" path: users select cloud or
    # local explicitly, and this process only continues after either persists.
    unified_result = _run_unified_setup()
    if unified_result:
        return True

    # Development fallback when the standalone chooser was not built yet.
    try:
        res = _show_api_setup_wizard(initial_status=wizard_status)
        if res["key"] or res.get("code"):
            _write_cloud_config(
                "deepseek",
                res["key"] or "",
                res.get("base", ""),
            )
            # 写入 setup_done 标志（同时兼容 model_downloader 的检测）
            import json

            flag = APP_ROOT / "config" / "model_setup_done.json"
            flag.write_text(json.dumps({"done": True, "version": 1}), encoding="utf-8")
            return True
        return False
    except Exception as e:
        try:
            (APP_ROOT / "logs" / "setup_error.log").write_text(
                f"Setup wizard error: {e}", encoding="utf-8"
            )
        except Exception:
            pass
        return False


# ── 本地模型安装提示（首次启动，可选）────────────────
def _prompt_local_model_if_needed():
    """
    首次启动时，如果 Ollama 未运行且用户尚未被提示过，
    弹窗询问是否安装本地 AI 模型助手。
    仅当 LocalModelInstaller.exe 存在时才触发（便携版/安装版均适用）。
    """
    import socket as _socket

    prompt_flag = APP_ROOT / "config" / "local_model_prompted.json"
    legacy_prompt_flag = APP_ROOT / "config" / "local_model_prompt_shown.flag"
    if prompt_flag.exists() or legacy_prompt_flag.exists():
        return  # 已提示过，跳过

    installer_exe = APP_ROOT / "LocalModelInstaller.exe"
    if not installer_exe.exists():
        return  # 没有安装程序，无法安装

    # 快速检测 Ollama 是否已在运行（11434 端口）
    try:
        _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _s.settimeout(0.5)
        _ollama_up = _s.connect_ex(("127.0.0.1", 11434)) == 0
        _s.close()
    except Exception:
        _ollama_up = False

    if _ollama_up:
        # Ollama 已在运行，标记为已提示，直接跳过
        try:
            import json as _json

            prompt_flag.write_text(
                _json.dumps({"prompted": True, "skipped": "ollama_running"}),
                encoding="utf-8",
            )
        except Exception:
            pass
        return

    # ── 弹出提示对话框 ──
    try:
        import tkinter as tk

        _chosen = {"action": None}

        dialog = tk.Tk()
        dialog.title("本地 AI 模型（可选）")
        dialog.resizable(False, False)
        dialog.configure(bg="#05080f")

        W, H = 420, 210
        dialog.geometry(f"{W}x{H}")
        dialog.update_idletasks()
        sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        dialog.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(200, lambda: dialog.attributes("-topmost", False))

        try:
            ico = ASSETS_DIR / "koto_icon.ico"
            if ico.exists():
                dialog.iconbitmap(str(ico))
        except Exception:
            pass

        tk.Label(
            dialog,
            text="是否安装本地 AI 模型助手？",
            bg="#05080f",
            fg="#e8eefc",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(22, 6))

        tk.Label(
            dialog,
            text="本地模型可加速任务分类，无需联网即可运行。\n需额外下载约 2–8 GB 模型文件。\n（可随时在 Koto 设置中安装或卸载）",
            bg="#05080f",
            fg="#9fb3d1",
            font=("Microsoft YaHei UI", 10),
            justify="center",
        ).pack(pady=(0, 18))

        btn_frame = tk.Frame(dialog, bg="#05080f")
        btn_frame.pack()

        def _on_install():
            _chosen["action"] = "install"
            dialog.destroy()

        def _on_skip():
            _chosen["action"] = "skip"
            dialog.destroy()

        tk.Button(
            btn_frame,
            text="立即安装",
            command=_on_install,
            bg="#1a6fcf",
            fg="#ffffff",
            activebackground="#2280e8",
            font=("Microsoft YaHei UI", 10, "bold"),
            relief="flat",
            bd=0,
            padx=18,
            pady=6,
            cursor="hand2",
        ).pack(side="left", padx=(0, 12))

        tk.Button(
            btn_frame,
            text="稍后再说",
            command=_on_skip,
            bg="#1a2540",
            fg="#9fb3d1",
            activebackground="#243055",
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            bd=0,
            padx=18,
            pady=6,
            cursor="hand2",
        ).pack(side="left")

        dialog.protocol("WM_DELETE_WINDOW", _on_skip)
        dialog.mainloop()

        # 写入已提示标志（无论选择如何，避免重复弹窗）
        import json as _json
        import subprocess as _subprocess

        prompt_flag.write_text(
            _json.dumps({"prompted": True, "action": _chosen["action"]}),
            encoding="utf-8",
        )

        if _chosen["action"] == "install":
            _subprocess.Popen([str(installer_exe)], cwd=str(APP_ROOT))

    except Exception:
        # 弹窗失败不阻塞启动
        pass


def _write_prerequisite_log(message: str) -> None:
    try:
        log_path = APP_ROOT / "logs" / "startup_prerequisites.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def _ensure_desktop_runtime() -> bool:
    """Install packaged desktop prerequisites before pywebview is imported."""
    try:
        from src.webview2_runtime import ensure_webview2_runtime
    except ImportError:
        from webview2_runtime import ensure_webview2_runtime

    ok, detail = ensure_webview2_runtime(APP_ROOT, log=_write_prerequisite_log)
    if ok:
        return True

    message = (
        "Koto 需要 Microsoft WebView2 Runtime 来显示桌面界面。\n\n"
        f"自动安装未完成：{detail}\n\n"
        "请重新运行安装包，或双击安装目录中的 "
        "Install_WebView2_Runtime.bat 后再启动 Koto。\n\n"
        f"诊断日志：{APP_ROOT / 'logs' / 'startup_prerequisites.log'}"
    )
    _write_prerequisite_log("ERROR: " + detail)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Koto 启动依赖缺失", message)
        root.destroy()
    except Exception:
        pass
    return False


# ── 主程序入口 ────────────────────────────────────────
def main():
    # In server-only mode, skip all interactive setup and go straight to app
    if os.environ.get("KOTO_SERVER_ONLY") != "1":
        # Step 1: 安装版/便携版自行补齐界面运行时，不依赖用户环境。
        if not _ensure_desktop_runtime():
            return
        # Step 2: 首次必须选择云端 API 或本地模型；未完成则不启动空壳应用。
        if not _run_setup_if_needed():
            return

    # Step 3: 启动 Koto 桌面程序
    # 兼容 src/ 布局：先找项目根，再找 src/ 子目录
    koto_main_path = BUNDLE_DIR / "koto_app.py"
    if not koto_main_path.exists():
        koto_main_path = BUNDLE_DIR / "src" / "koto_app.py"
    if koto_main_path.exists():
        # 开发模式：直接 runpy
        os.chdir(str(APP_ROOT))
        runpy.run_path(str(koto_main_path), run_name="__main__")
    else:
        # 打包后：koto_app 已编译进 exe，直接导入调用
        os.chdir(str(APP_ROOT))
        try:
            import koto_app

            koto_app.main()
        except Exception as e:
            # 崩溃时写日志并弹窗
            err_msg = f"Koto 启动失败:\n{e}"
            try:
                (APP_ROOT / "logs" / "crash.log").write_text(err_msg, encoding="utf-8")
            except Exception:
                pass
            try:
                import tkinter as tk
                from tkinter import messagebox

                _root = tk.Tk()
                _root.withdraw()
                messagebox.showerror("Koto 启动失败", err_msg)
                _root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    # ── Step 1: PyInstaller 冻结环境必须：在 main() 之前调用 freeze_support ──
    # 当 torch / transformers / datasets 等库通过 multiprocessing 产生子进程时，
    # 子进程会重新执行冻结的 exe。freeze_support() 检测到子进程标志后立即接管
    # 并退出，防止子进程再次执行 main() 打开新 Koto 窗口。
    import multiprocessing

    multiprocessing.freeze_support()

    # ── Step 2: Windows 全局 Mutex 单实例锁 ──────────────────────────────────
    # freeze_support() 处理 multiprocessing 工作进程，但无法拦截所有子进程类型。
    # 这里再加一道保险：用命名 Mutex 确保只有一个 Koto 主窗口实例在运行。
    # 这对所有子进程（包括 pystray、pythonnet/WebView2 产生的子进程）都有效。
    _mutex_handle = None
    # Service-only release checks do not create a desktop window, so they do
    # not compete with a user's already-running desktop instance.
    if sys.platform == "win32" and os.environ.get("KOTO_SERVER_ONLY") != "1":
        try:
            import ctypes
            import ctypes.wintypes

            # 创建全局命名互斥量（不拥有它，只检测是否已存在）
            _MUTEX_NAME = "Global\\KotoMainWindowMutex_v1"
            _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
            _last_err = ctypes.windll.kernel32.GetLastError()
            if _last_err == 183:  # ERROR_ALREADY_EXISTS
                # Koto 已经在运行，将已有窗口前置并退出
                print("[Koto] 检测到已有实例在运行，退出本次启动。")
                # 尝试激活已有窗口
                try:
                    import win32gui

                    def _find_koto_window(hwnd, extra):
                        title = win32gui.GetWindowText(hwnd)
                        if "Koto" in title and win32gui.IsWindowVisible(hwnd):
                            win32gui.SetForegroundWindow(hwnd)
                            return False
                        return True

                    win32gui.EnumWindows(_find_koto_window, None)
                except Exception:
                    pass
                sys.exit(0)
        except Exception as _mutex_err:
            # Mutex 创建失败不影响程序运行，只是失去单实例保护
            print(f"[Koto] Mutex 创建失败（非致命）: {_mutex_err}")

    main()
