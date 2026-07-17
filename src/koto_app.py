#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto 桌面应用 - 独立窗口版本
使用 pywebview 创建原生窗口，Flask 作为后端
无终端，完全独立运行
"""

import faulthandler
import logging
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import psutil

try:
    from src.runtime_bootstrap import (
        configure_process_environment,
        resolve_runtime_roots,
    )
except ImportError:
    from runtime_bootstrap import configure_process_environment, resolve_runtime_roots

logger = logging.getLogger(__name__)

KOTO_HOST = "127.0.0.1"
KOTO_PORT = int(os.environ.get("KOTO_PORT", "5000"))
FALLBACK_PORT = int(os.environ.get("KOTO_FALLBACK_PORT", "5001"))
STARTUP_FAST_READY_SEC = float(os.environ.get("KOTO_STARTUP_FAST_READY_SEC", "3"))
STARTUP_HARD_TIMEOUT_SEC = float(os.environ.get("KOTO_STARTUP_TIMEOUT_SEC", "120"))
WINDOW_RECOVERY_COUNT_ENV = "KOTO_WINDOW_RECOVERY_COUNT"
WINDOW_RECOVERY_MAX_ENV = "KOTO_MAX_UNEXPECTED_WINDOW_RECOVERY"
BACKEND_RECOVERY_COUNT_ENV = "KOTO_BACKEND_RECOVERY_COUNT"
BACKEND_RECOVERY_MAX_ENV = "KOTO_MAX_BACKEND_RECOVERY"
BACKEND_WATCHDOG_ENABLED_ENV = "KOTO_ENABLE_BACKEND_WATCHDOG"
BACKEND_WATCHDOG_INTERVAL_ENV = "KOTO_BACKEND_WATCHDOG_INTERVAL_SEC"
BACKEND_WATCHDOG_MAX_FAILURES_ENV = "KOTO_BACKEND_WATCHDOG_MAX_FAILURES"

# 获取应用根目录和资源目录
ROOTS = resolve_runtime_roots(__file__)
APP_ROOT = ROOTS.app_root
BUNDLE_DIR = ROOTS.bundle_dir

if getattr(sys, "frozen", False):
    # PyInstaller打包后：
    # - APP_ROOT: exe所在目录（用于持久化数据：chats/、config/、workspace/等）
    # - BUNDLE_DIR: 临时解压目录（用于bundled资源：web/、assets/等）
    # Fix pythonnet runtime path for pywebview's EdgeChromium backend in frozen environment
    # pythonnet needs to know where the Python runtime is located
    _internal_py = APP_ROOT / "internal" / "py"
    if _internal_py.exists():
        os.environ.setdefault(
            "PYTHONNET_PYDLL",
            str(
                _internal_py
                / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
            ),
        )
    # Alternative: Force pywebview to use EdgeChromium without pythonnet initialization issues
    os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")


# 图标资源目录：打包模式下在 _MEIPASS/assets/，源码模式下在 src/assets/
ASSETS_DIR = (
    BUNDLE_DIR if getattr(sys, "frozen", False) else APP_ROOT / "src"
) / "assets"

configure_process_environment(
    ROOTS,
    prepend_paths=(BUNDLE_DIR,),
    required_dirs=("logs", "chats", "workspace", "config"),
)

LOG_FILE = APP_ROOT / "logs" / "startup.log"
RUNTIME_LOG_FILE = (
    APP_ROOT / "logs" / f"runtime_{datetime.now().strftime('%Y%m%d')}.log"
)


class DualOutput:
    """同时输出到文件和控制台 - 使用持久文件句柄，避免每次 write 都 open/close"""

    def __init__(self, original_stream, log_file):
        self.original_stream = original_stream
        self.log_file = log_file
        self._file = None
        self._lock = threading.Lock()
        try:
            self._file = open(
                log_file, "a", encoding="utf-8", errors="ignore", buffering=1
            )
        except Exception:
            pass

    def write(self, message):
        try:
            self.original_stream.write(message)
            if self._file:
                with self._lock:
                    self._file.write(message)
        except Exception:
            pass

    def flush(self):
        try:
            self.original_stream.flush()
            if self._file:
                self._file.flush()
        except Exception:
            pass

    def close(self):
        try:
            if self._file:
                self._file.close()
                self._file = None
        except Exception:
            pass


def _redirect_output():
    """将 stdout/stderr 重定向到日志文件"""
    try:
        RUNTIME_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 写入分隔符
        with open(RUNTIME_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n\n{'='*30} New Session {datetime.now()} {'='*30}\n")

        sys.stdout = DualOutput(sys.stdout, RUNTIME_LOG_FILE)
        sys.stderr = DualOutput(sys.stderr, RUNTIME_LOG_FILE)
        print(f"Log redirected to {RUNTIME_LOG_FILE}")
    except Exception as e:
        print(f"Failed to redirect output: {e}")


_redirect_output()

# 持久化启动日志文件句柄，避免每次 _write_log 都 open/close（性能优化）
_startup_log_file = None
_startup_log_lock = threading.Lock()
_shutdown_reason = None
_shutdown_lock = threading.Lock()


def _get_startup_log():
    """懒加载并缓存启动日志文件句柄"""
    global _startup_log_file
    if _startup_log_file is None:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _startup_log_file = LOG_FILE.open("a", encoding="utf-8", buffering=1)
        except Exception:
            pass
    return _startup_log_file


def _write_log(message: str):
    """写入启动日志并同步打印，便于定位"未响应"原因"""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}\n"
        f = _get_startup_log()
        if f:
            with _startup_log_lock:
                f.write(line)
        print(message)
    except Exception:
        # 日志失败不应阻塞启动
        pass


def _request_app_shutdown(reason: str):
    global _shutdown_reason
    with _shutdown_lock:
        _shutdown_reason = reason


def _clear_app_shutdown_request():
    global _shutdown_reason
    with _shutdown_lock:
        _shutdown_reason = None


def _get_app_shutdown_reason():
    with _shutdown_lock:
        return _shutdown_reason


def _set_window_icon(icon_path=None):
    if not icon_path:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Koto - AI 个人助手")
        if not hwnd:
            return

        # Load the .ico file as a Windows icon handle
        # Use LoadImageW with IMAGE_ICON (1) | LR_LOADFROMFILE (16)
        LR_LOADFROMFILE = 0x00000010
        IMAGE_ICON = 1
        hIcon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if hIcon:
            WM_SETICON = 0x0080
            ICON_BIG = 1
            ICON_SMALL = 0
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hIcon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hIcon)
            _write_log(f"✔ 窗口图标已设置: {icon_path}")
    except Exception as e:
        _write_log(f"⚠️ 设置窗口图标失败: {e}")


def _handle_webview_exit():
    shutdown_reason = _get_app_shutdown_reason()
    if shutdown_reason:
        _write_log(f"ℹ️ webview.start 结束（窗口已关闭，原因={shutdown_reason}）")
        return os._exit(0)

    _write_log("⚠️ webview.start 非显式结束，可能是窗口或渲染进程异常关闭")
    _dump_threads("unexpected-webview-exit")

    try:
        max_recovery = max(0, int(os.environ.get(WINDOW_RECOVERY_MAX_ENV, "1")))
    except Exception:
        max_recovery = 1
    try:
        recovery_count = max(0, int(os.environ.get(WINDOW_RECOVERY_COUNT_ENV, "0")))
    except Exception:
        recovery_count = 0

    if recovery_count < max_recovery:
        env = os.environ.copy()
        env[WINDOW_RECOVERY_COUNT_ENV] = str(recovery_count + 1)
        env["KOTO_WINDOW_LAST_EXIT_REASON"] = "unexpected_webview_exit"
        _write_log(
            f"🔄 检测到窗口异常结束，尝试自动恢复 ({recovery_count + 1}/{max_recovery})"
        )
        os.execve(sys.executable, [sys.executable] + sys.argv, env)
        return

    _write_log("❌ 已达到窗口自动恢复上限，退出进程")
    return os._exit(1)


def _attempt_process_recovery(
    reason: str,
    *,
    count_env: str,
    max_env: str,
    default_max: int = 1,
) -> bool:
    try:
        max_recovery = max(0, int(os.environ.get(max_env, str(default_max))))
    except Exception:
        max_recovery = max(0, int(default_max))

    try:
        recovery_count = max(0, int(os.environ.get(count_env, "0")))
    except Exception:
        recovery_count = 0

    if recovery_count >= max_recovery:
        _write_log(f"❌ 已达到 {reason} 自动恢复上限，停止自动恢复")
        return False

    env = os.environ.copy()
    env[count_env] = str(recovery_count + 1)
    env["KOTO_LAST_RECOVERY_REASON"] = reason
    _write_log(
        f"🔄 检测到 {reason}，尝试自动恢复 ({recovery_count + 1}/{max_recovery})"
    )
    os.execve(sys.executable, [sys.executable] + sys.argv, env)
    return True


def _backend_watchdog_enabled() -> bool:
    value = os.environ.get(BACKEND_WATCHDOG_ENABLED_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _start_backend_health_watchdog(
    health_url: str,
    *,
    server_thread=None,
    expect_server_thread: bool = False,
    interval_sec: float | None = None,
    max_failures: int | None = None,
):
    if not health_url:
        return None

    try:
        interval = float(
            interval_sec
            if interval_sec is not None
            else os.environ.get(BACKEND_WATCHDOG_INTERVAL_ENV, "5")
        )
    except Exception:
        interval = 5.0
    interval = max(interval, 0.5)

    try:
        failures_limit = int(
            max_failures
            if max_failures is not None
            else os.environ.get(BACKEND_WATCHDOG_MAX_FAILURES_ENV, "3")
        )
    except Exception:
        failures_limit = 3
    failures_limit = max(failures_limit, 1)

    def _watch():
        consecutive_failures = 0
        while True:
            if _get_app_shutdown_reason():
                return

            thread_alive = True
            if expect_server_thread and server_thread is not None:
                try:
                    thread_alive = server_thread.is_alive()
                except Exception:
                    thread_alive = False

            health_ok = _check_koto_health(health_url, timeout=min(interval, 0.5))
            if health_ok and thread_alive:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                _write_log(
                    "⚠️ 后端健康检查失败 "
                    f"({consecutive_failures}/{failures_limit}) "
                    f"health_ok={health_ok} thread_alive={thread_alive}"
                )
                if consecutive_failures >= failures_limit:
                    _dump_threads("backend-health-watchdog")
                    _attempt_process_recovery(
                        "backend_unreachable",
                        count_env=BACKEND_RECOVERY_COUNT_ENV,
                        max_env=BACKEND_RECOVERY_MAX_ENV,
                        default_max=1,
                    )
                    return

            time.sleep(interval)

    watchdog = threading.Thread(
        target=_watch,
        daemon=True,
        name="koto-backend-health-watchdog",
    )
    watchdog.start()
    return watchdog


def _dump_threads(label: str = "thread-dump"):
    """将当前进程的线程栈写入日志，方便定位卡死位置"""
    try:
        f = _get_startup_log()
        if f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with _startup_log_lock:
                f.write(f"\n===== {label} {ts} =====\n")
                faulthandler.dump_traceback(file=f, all_threads=True)
    except Exception:
        traceback.print_exc()


def _terminate_stale_process_on_port(port: int, reason: str = "") -> bool:
    """Terminate only an unhealthy Koto process from this exact app root.

    A generic ``pythonw`` listener may belong to an unrelated application and
    must never be killed merely because it uses Koto's preferred port.
    """
    killed = False
    try:
        # 快速预检：通过 socket 确认端口已被占用，否则直接跳过全量扫描
        _pre = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _pre.settimeout(0.1)
        _port_in_use = _pre.connect_ex(("127.0.0.1", port)) == 0
        _pre.close()
        if not _port_in_use:
            return False

        for conn in psutil.net_connections(kind="inet"):
            if (
                conn.laddr
                and conn.laddr.port == port
                and conn.status == psutil.CONN_LISTEN
            ):
                pid = conn.pid
                if not pid:
                    continue
                try:
                    proc = psutil.Process(pid)
                    cmdline = " ".join(proc.cmdline()).lower()
                    process_name = proc.name().lower()
                    try:
                        process_exe = Path(proc.exe()).resolve()
                    except (OSError, psutil.Error):
                        process_exe = None
                    expected_exe = (APP_ROOT / "Koto.exe").resolve()
                    same_frozen_app = (
                        process_name == "koto.exe" and process_exe == expected_exe
                    )
                    app_root_marker = str(APP_ROOT.resolve()).lower()
                    same_source_app = (
                        app_root_marker in cmdline
                        and (
                            "koto_app.py" in cmdline
                            or "web\\app.py" in cmdline
                            or "web/app.py" in cmdline
                        )
                    )
                    if same_frozen_app or same_source_app:
                        _write_log(f"⚠️ 终止占用 {port} 的进程 {pid}（{reason}）")
                        proc.kill()
                        time.sleep(0.5)  # 0.5s 通常足够进程退出
                        killed = True
                except Exception:
                    pass
    except Exception as e:
        _write_log(f"⚠️ 检查端口占用失败: {e}")
    return killed


def _check_http_ok(url: str, timeout: float = 2.0) -> bool:
    """Return whether an arbitrary local HTTP page responds successfully."""
    try:
        from urllib.request import ProxyHandler, build_opener, urlopen

        opener = build_opener(ProxyHandler({}))  # 禁用系统代理，避免被本地代理劫持误判
        with opener.open(url, timeout=max(float(timeout or 0), 0.05)) as resp:
            return resp.status == 200
    except Exception:
        return False


def _check_koto_health(url: str, timeout: float = 2.0) -> bool:
    """Validate Koto's JSON health contract, not merely an HTTP 200 page."""
    try:
        import json
        from urllib.request import ProxyHandler, build_opener

        opener = build_opener(ProxyHandler({}))
        with opener.open(url, timeout=max(float(timeout or 0), 0.05)) as resp:
            if resp.status != 200:
                return False
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, dict):
            return False
        status = str(payload.get("status") or "").strip().lower()
        return payload.get("success") is True or status in {
            "ok",
            "healthy",
            "degraded",
        }
    except (OSError, ValueError, TypeError):
        return False


def _wait_for_http_ok(
    url: str,
    timeout_sec: float,
    *,
    request_timeout: float = 0.5,
    poll_interval: float = 0.25,
) -> bool:
    """等待健康检查通过，并确保总等待时间不会被单次请求超时放大。"""
    deadline = time.monotonic() + max(float(timeout_sec or 0), 0.0)
    request_timeout = max(float(request_timeout or 0), 0.05)
    poll_interval = max(float(poll_interval or 0), 0.05)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False

        timeout = min(request_timeout, remaining)
        if _check_http_ok(url, timeout=timeout):
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll_interval, remaining))


def _wait_for_koto_health(
    url: str,
    timeout_sec: float,
    *,
    request_timeout: float = 0.5,
    poll_interval: float = 0.25,
) -> bool:
    """Wait for the structured Koto health contract."""
    deadline = time.monotonic() + max(float(timeout_sec or 0), 0.0)
    request_timeout = max(float(request_timeout or 0), 0.05)
    poll_interval = max(float(poll_interval or 0), 0.05)
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if _check_koto_health(url, timeout=min(request_timeout, remaining)):
            return True
        time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0.0)))
    return False


def _find_available_port(host: str, start_port: int, max_tries: int = 20) -> int | None:
    """从 start_port 开始查找可用端口，返回端口号或 None。"""
    for port in range(start_port, start_port + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) != 0:
                    return port
        except Exception:
            continue
    return None


def ensure_directories():
    """确保必要的目录存在"""
    dirs = [
        "workspace",
        "workspace/images",
        "workspace/documents",
        "workspace/code",
        "chats",
        "logs",
        "config",
    ]
    for d in dirs:
        (APP_ROOT / d).mkdir(exist_ok=True, parents=True)

    bundled_config = BUNDLE_DIR / "config"
    runtime_config = APP_ROOT / "config"
    if bundled_config.exists() and bundled_config != runtime_config:
        import shutil

        copied_files = 0
        created_dirs = 0
        for src_dir, _, filenames in os.walk(bundled_config):
            src_path = Path(src_dir)
            rel_path = src_path.relative_to(bundled_config)
            dst_path = runtime_config / rel_path
            if not dst_path.exists():
                dst_path.mkdir(parents=True, exist_ok=True)
                created_dirs += 1

            for filename in filenames:
                src_file = src_path / filename
                dst_file = dst_path / filename
                if dst_file.exists():
                    continue
                try:
                    shutil.copy2(src_file, dst_file)
                    copied_files += 1
                except Exception as exc:
                    _write_log(f"⚠️ 同步默认配置失败: {src_file.name} -> {exc}")

        if copied_files or created_dirs:
            _write_log(
                f"✔ 已同步默认配置到运行目录: {copied_files} 个文件, {created_dirs} 个目录"
            )

    _write_log("✔ 目录检查完成")


def check_config():
    """检查配置文件"""
    config_file = APP_ROOT / "config" / "deepseek_config.env"
    if not config_file.exists():
        config_file.parent.mkdir(exist_ok=True, parents=True)
        config_file.write_text(
            "# Koto Configuration\n"
            "DEEPSEEK_API_KEY=your_api_key_here\n"
            "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
        )
        _write_log("⚠️ 未检测到 deepseek_config.env，已生成占位文件")
    else:
        _write_log("✔ 配置文件存在")


def ensure_dependencies():
    """Verify that build-time desktop dependencies are present in this bundle."""
    import importlib.util

    missing = []
    if importlib.util.find_spec("webview") is None:
        missing.append("pywebview")
    if (
        importlib.util.find_spec("pystray") is None
        or importlib.util.find_spec("PIL") is None
    ):
        missing.append("pystray/pillow")

    if missing:
        detail = ", ".join(missing)
        if getattr(sys, "frozen", False):
            _write_log(f"❌ 发布包缺少内置桌面组件: {detail}；请重新安装 Koto")
        else:
            _write_log(f"❌ 开发环境缺少桌面组件: {detail}；请同步项目锁定依赖")
        return False
    _write_log("✔ 关键依赖就绪")
    return True


class VoiceAPI:
    """Compatibility facade for the upload-based STT API."""

    def __init__(self):
        pass

    def get_available_engines(self):
        """Return the supported upload-based STT engines."""
        try:
            from app.core.services.local_stt import get_status

            local = get_status()
        except Exception as e:
            logger.debug("Failed to get local STT status: %s", e)
            local = {"available": False, "engine": "unavailable"}

        engines = []
        if local.get("available"):
            engines.insert(
                0,
                {
                    "id": str(local.get("engine") or "local"),
                    "name": "Local upload STT",
                    "available": True,
                },
            )
        return engines


class WindowAPI:
    """窗口控制API - 提供给前端调用"""

    def __init__(self, window, base_url):
        self.window = window
        self.base_url = base_url.rstrip("/")
        self.is_mini_mode = False
        self.full_size = (1200, 800)
        self.full_pos = None
        self.mini_size = (320, 480)  # 适合高分辨率屏幕的迷你尺寸
        self._force_close_flag = False  # Set by force_close() to skip unsaved-check
        # Python-side mirror of unsaved files: {path_or_key: display_name}
        # JS updates this via mark_file_modified() so _on_closing never needs evaluate_js
        # for the common "nothing dirty" path.
        self._unsaved_files: dict = {}

    def _get_logical_screen_size(self):
        """返回逻辑像素下的屏幕尺寸（pywebview.move/resize 使用逻辑像素坐标）。
        GetSystemMetrics 在 DPI-aware 进程中返回物理像素，需除以 DPI 缩放比例。
        """
        import ctypes

        user32 = ctypes.windll.user32
        physical_w = user32.GetSystemMetrics(0)
        physical_h = user32.GetSystemMetrics(1)
        try:
            get_dpi = ctypes.windll.user32.GetDpiForSystem
            get_dpi.restype = ctypes.c_uint
            dpi = get_dpi()
            scale = dpi / 96.0
        except AttributeError:
            # Windows < 8.1 fallback: 用 GDI 查询 DPI
            try:
                hdc = ctypes.windll.gdi32.CreateDCW("DISPLAY", None, None, None)
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                ctypes.windll.gdi32.DeleteDC(hdc)
                scale = dpi / 96.0
            except Exception:
                scale = 1.0
        return int(physical_w / scale), int(physical_h / scale)

    def _navigate_after_return(self, url, delay=0.15):
        """延后导航，让当前 HTTP/JS 调用先完成，避免回调和页面跳转互相阻塞。"""

        def _load_target():
            import time

            if delay > 0:
                time.sleep(delay)
            self.window.load_url(url)

        threading.Thread(target=_load_target, daemon=True).start()

    def switch_to_mini(self):
        """切换到迷你模式 - 固定在屏幕右侧垂直居中"""
        if self.is_mini_mode:
            return {"success": True, "mode": "mini"}

        try:
            screen_w, screen_h = self._get_logical_screen_size()

            # 保存当前位置和大小，以便恢复
            self.full_size = (self.window.width, self.window.height)
            self.full_pos = (self.window.x, self.window.y)

            # 迷你窗口固定在屏幕右侧，垂直居中，留 20px 边距
            mini_w, mini_h = self.mini_size
            x = max(0, screen_w - mini_w - 20)
            y = max(20, (screen_h - mini_h) // 2)

            self.is_mini_mode = True

            def _do_switch():
                import time

                time.sleep(0.15)
                try:
                    # 先移动再调整大小，确保位置正确
                    self.window.move(x, y)
                    self.window.resize(mini_w, mini_h)
                    self.window.on_top = True
                    self.window.load_url(f"{self.base_url}/mini")
                except Exception as ex:
                    logger.debug("Failed to switch to mini mode ui: %s", ex)

            import threading

            threading.Thread(target=_do_switch, daemon=True).start()

            return {
                "success": True,
                "mode": "mini",
                "size": [mini_w, mini_h],
                "pos": [x, y],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def switch_to_full(self):
        """切换到完整模式，恢复切换前的位置"""
        if not self.is_mini_mode:
            return {"success": True, "mode": "full"}

        try:
            full_w, full_h = self.full_size

            # 优先恢复切换前的位置，否则居中
            if self.full_pos is not None:
                x, y = self.full_pos
            else:
                screen_w, screen_h = self._get_logical_screen_size()
                x = max(0, (screen_w - full_w) // 2)
                y = max(0, (screen_h - full_h) // 2)

            self.is_mini_mode = False

            def _do_switch():
                import time

                time.sleep(0.15)
                try:
                    self.window.on_top = False
                    self.window.resize(full_w, full_h)
                    self.window.move(x, y)
                    self.window.load_url(self.base_url)
                except Exception as ex:
                    logger.debug("Failed to switch to full mode ui: %s", ex)

            import threading

            threading.Thread(target=_do_switch, daemon=True).start()

            return {"success": True, "mode": "full"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_mode(self):
        """获取当前模式"""
        return {"mode": "mini" if self.is_mini_mode else "full"}

    def minimize(self):
        """最小化窗口"""
        self.window.minimize()

    def maximize(self):
        """最大化/还原窗口"""
        try:
            # pywebview没有直接的maximize，用toggle_fullscreen替代
            self.window.toggle_fullscreen()
        except Exception as e:
            logger.debug("Failed to toggle fullscreen: %s", e)

    def close(self):
        """关闭窗口（来自JS调用）— 先在JS层检查未保存文件，再销毁"""
        _request_app_shutdown("js_close")
        try:
            self.window.destroy()
        except Exception:
            _clear_app_shutdown_request()
            raise

    def force_close(self):
        """强制关闭窗口 — 绕过未保存检查，由JS关闭确认对话框调用"""
        self._force_close_flag = True
        _request_app_shutdown("js_force_close")
        try:
            self.window.destroy()
        except Exception:
            _clear_app_shutdown_request()
            raise

    def mark_file_modified(self, path: str, name: str, modified: bool):
        """JS 每次改变 tab.modified 时调用此方法，保持 Python 侧状态同步。
        这样 _on_closing 在无未保存文件的普通关闭路径上无需调用 evaluate_js，
        避免 EdgeChromium COM 线程与后台线程之间的死锁（"未响应"根本原因）。"""
        key = path or name
        if modified:
            self._unsaved_files[key] = name
        else:
            self._unsaved_files.pop(key, None)
        return True

    def open_url(self, url: str):
        """在系统默认浏览器中打开外部链接，防止 webview 导航离开 Koto"""
        import webbrowser
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return {"success": False, "error": "不允许的协议"}
            if not parsed.netloc:
                return {"success": False, "error": "无效的URL（缺少域名）"}
            webbrowser.open(url)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}


def _pre_check_syntax(filepath: str):
    """
    预检查 Python 文件语法，在 import 之前发现问题。
    返回 (True/False, error_message)
    """
    import ast

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        ast.parse(source, filename=filepath)
        return True, None
    except SyntaxError as e:
        error_msg = f"{e.msg} ({os.path.basename(filepath)}, line {e.lineno})"
        return False, error_msg
    except Exception as e:
        return False, str(e)


def start_flask_server():
    """Start the packaged Flask backend and expose live startup state."""
    global KOTO_PORT

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    health_url = f"http://{KOTO_HOST}:{KOTO_PORT}/api/health"
    reuse_healthy_backend = os.environ.get("KOTO_REUSE_HEALTHY_BACKEND", "0") == "1"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            port_in_use = sock.connect_ex((KOTO_HOST, KOTO_PORT)) == 0
        if port_in_use:
            if _check_koto_health(health_url):
                if reuse_healthy_backend:
                    _write_log(
                        f"ℹ️ 检测到 {KOTO_HOST}:{KOTO_PORT} 已在运行，健康检查通过，跳过内置服务启动"
                    )
                    return {
                        "started": False,
                        "already_running": True,
                        "phase": "ready",
                        "error": None,
                    }

                alt_port = _find_available_port(KOTO_HOST, FALLBACK_PORT)
                if alt_port is None:
                    _write_log(
                        f"ℹ️ {KOTO_HOST}:{KOTO_PORT} 已有健康 Koto 后端且无备用端口，复用现有实例"
                    )
                    return {
                        "started": False,
                        "already_running": True,
                        "phase": "ready",
                        "error": None,
                    }
                _write_log(
                    f"ℹ️ {KOTO_HOST}:{KOTO_PORT} 已有健康 Koto 后端；当前窗口改用端口 {alt_port}"
                )
                KOTO_PORT = alt_port
            else:
                _write_log(
                    f"⚠️ {KOTO_HOST}:{KOTO_PORT} 被占用但健康检查失败，尝试清理占用进程"
                )
                cleaned = _terminate_stale_process_on_port(
                    KOTO_PORT, reason="health timeout"
                )
                if cleaned:
                    _write_log("ℹ️ 已清理占用进程，继续启动内置服务")
                else:
                    alt_port = _find_available_port(KOTO_HOST, FALLBACK_PORT)
                    if alt_port is None:
                        message = (
                            f"{KOTO_HOST}:{KOTO_PORT} 被其他程序占用，且没有可用备用端口"
                        )
                        _write_log(f"❌ {message}")
                        return {
                            "started": False,
                            "already_running": False,
                            "needs_fallback": True,
                            "phase": "port allocation failed",
                            "error": message,
                        }
                    _write_log(f"⚠️ 清理失败，自动改用可用端口 {alt_port}")
                    KOTO_PORT = alt_port
    except Exception as exc:
        _write_log(f"⚠️ 检查端口状态失败，继续尝试启动: {exc}")

    server_info = {
        "started": True,
        "already_running": False,
        "phase": "preparing backend import",
        "error": None,
        "traceback": None,
        "started_at": time.monotonic(),
    }

    def run_server():
        try:
            app_file = os.path.join(str(BUNDLE_DIR), "web", "app.py")
            debug_syntax = os.environ.get("KOTO_DEBUG_SYNTAX", "0") == "1"
            if debug_syntax and os.path.exists(app_file):
                server_info["phase"] = "checking packaged web application syntax"
                _write_log("🔍 正在执行语法预检查...")
                syntax_ok, syntax_err = _pre_check_syntax(app_file)
                if not syntax_ok:
                    raise SyntaxError(syntax_err)
            else:
                _write_log("⚡ 快速启动：跳过语法预检查")

            server_info["phase"] = "importing packaged web application"
            _write_log("⏳ 正在导入 Koto 后端...")
            from web.app import app, socketio

            server_info["phase"] = "binding local HTTP service"
            _write_log(f"⏳ 正在监听 http://{KOTO_HOST}:{KOTO_PORT}")
            if socketio is not None:
                socketio.run(
                    app,
                    host=KOTO_HOST,
                    port=KOTO_PORT,
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True,
                )
            else:
                app.run(
                    host=KOTO_HOST,
                    port=KOTO_PORT,
                    debug=False,
                    use_reloader=False,
                    threaded=True,
                )
            if server_info.get("error") is None:
                server_info["error"] = "Koto 后端服务意外退出"
                server_info["phase"] = "backend exited"
        except Exception as exc:
            message = (
                f"语法错误: {exc}"
                if isinstance(exc, SyntaxError)
                else f"{type(exc).__name__}: {exc}"
            )
            server_info["error"] = message
            server_info["traceback"] = traceback.format_exc()
            server_info["phase"] = "backend startup failed"
            _write_log(f"❌ Flask 服务启动失败: {message}")
            _write_log(server_info["traceback"])

    server_thread = threading.Thread(
        target=run_server,
        name="KotoFlaskBackend",
        daemon=True,
    )
    server_info["thread"] = server_thread
    server_thread.start()
    _write_log("✔ Flask 后台线程已启动")
    return server_info


def _startup_status_provider(server_info: dict, backend_url: str):
    """Build a pollable status provider for the startup window."""
    health_url = f"{backend_url}/api/health"
    started_at = float(server_info.get("started_at") or time.monotonic())

    def provide():
        if _check_koto_health(health_url, timeout=0.4):
            server_info["phase"] = "ready"
            return {"status": "ready", "phase": "ready", "target_url": backend_url}

        error = server_info.get("error")
        if error:
            return {
                "status": "error",
                "phase": server_info.get("phase") or "backend startup failed",
                "error": str(error),
                "target_url": backend_url,
            }

        thread = server_info.get("thread")
        if server_info.get("started") and thread is not None and not thread.is_alive():
            return {
                "status": "error",
                "phase": "backend thread exited",
                "error": "Koto 后端线程在开始监听前意外退出，请查看 startup.log",
                "target_url": backend_url,
            }

        elapsed = time.monotonic() - started_at
        if elapsed >= STARTUP_HARD_TIMEOUT_SEC:
            return {
                "status": "timeout",
                "phase": server_info.get("phase") or "initializing",
                "error": (
                    f"后端初始化已超过 {int(STARTUP_HARD_TIMEOUT_SEC)} 秒；"
                    "Koto 会继续等待，并已保留线程与错误日志"
                ),
                "target_url": backend_url,
            }

        return {
            "status": "starting",
            "phase": server_info.get("phase") or "initializing",
            "elapsed_seconds": round(elapsed, 1),
            "target_url": backend_url,
        }

    return provide


def _restart_current_process():
    _write_log("🔄 正在重启 Koto...")
    executable = sys.executable
    arguments = (
        [executable, *sys.argv[1:]]
        if getattr(sys, "frozen", False)
        else [executable, *sys.argv]
    )
    os.execve(executable, arguments, os.environ.copy())


def _start_startup_status_server(
    port: int,
    *,
    backend_url: str,
    server_info: dict,
):
    try:
        try:
            from src.startup_recovery import serve_startup_status
        except ImportError:
            from startup_recovery import serve_startup_status

        serve_startup_status(
            KOTO_HOST,
            port,
            app_root=APP_ROOT,
            bundle_dir=BUNDLE_DIR,
            backend_url=backend_url,
            status_provider=_startup_status_provider(server_info, backend_url),
            restart=_restart_current_process,
            log=_write_log,
        )
    except Exception as exc:
        _write_log(f"❌ 启动状态服务无法监听 {KOTO_HOST}:{port}: {exc}")


def create_system_tray(window_ref=None):
    """创建系统托盘图标"""
    try:
        from PIL import Image, ImageDraw
        from pystray import Icon, Menu, MenuItem

        icon_file = ASSETS_DIR / "koto_icon.png"

        def create_icon_image():
            """创建简单的托盘图标"""
            # 创建 64x64 图标
            width, height = 64, 64
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)

            # 绘制圆形背景 - 渐变蓝色
            draw.ellipse([4, 4, 60, 60], fill=(66, 133, 244, 255))

            # 绘制内部圆形 - 白色
            draw.ellipse([16, 16, 48, 48], fill=(255, 255, 255, 255))

            # 绘制 "言" 字形状的简化版本 - 三条横线
            draw.rectangle([22, 24, 42, 28], fill=(66, 133, 244, 255))
            draw.rectangle([22, 32, 42, 36], fill=(66, 133, 244, 255))
            draw.rectangle([22, 40, 42, 44], fill=(66, 133, 244, 255))

            return image

        def on_quit(icon, item):
            """退出应用"""
            if window_ref:
                try:
                    window_ref[0].destroy()
                    return
                except Exception as e:
                    logger.debug("Failed to destroy window from tray quit: %s", e)
            icon.stop()
            _request_app_shutdown("tray_quit")
            os._exit(0)

        def on_show(icon, item):
            """显示主窗口"""
            if window_ref:
                try:
                    window_ref[0].show()
                except Exception as e:
                    logger.debug("Failed to show window: %s", e)

        def on_hide(icon, item):
            """隐藏主窗口"""
            if window_ref:
                try:
                    window_ref[0].hide()
                except Exception as e:
                    logger.debug("Failed to hide window: %s", e)

        # 创建托盘图标（优先使用自定义图标）
        if icon_file.exists():
            tray_image = Image.open(str(icon_file))
        else:
            tray_image = create_icon_image()

        icon = Icon(
            "Koto",
            tray_image,
            "Koto - AI 助手 (运行中)",
            Menu(
                MenuItem("显示窗口", on_show, default=True),
                MenuItem("隐藏窗口", on_hide),
                Menu.SEPARATOR,
                MenuItem("退出", on_quit),
            ),
        )

        return icon
    except Exception as e:
        print(f"⚠️ 系统托盘创建失败: {e}")
        return None


def _bootstrap_api_setup() -> bool:
    """Run the shared first-run chooser before the desktop app starts."""
    if os.environ.get("KOTO_SERVER_ONLY") == "1":
        return True
    import json as _json

    # 抑制旧版编译入口下次弹出 model_downloader
    _flag = APP_ROOT / "config" / "model_setup_done.json"
    if not _flag.exists():
        try:
            _flag.write_text(
                _json.dumps({"done": True, "version": 1}), encoding="utf-8"
            )
        except Exception:
            pass
    # 调用 koto_setup.py 中的 API 密钥向导
    try:
        import runpy as _runpy

        _bundle = (
            Path(sys._MEIPASS)
            if getattr(sys, "frozen", False)
            else Path(__file__).parent
        )
        _setup_py = _bundle / "koto_setup.py"
        if _setup_py.exists():
            _ns = _runpy.run_path(
                str(_setup_py)
            )  # run_name 默认非 __main__，不触发 main()
            if "_run_setup_if_needed" in _ns:
                return bool(_ns["_run_setup_if_needed"]())
    except Exception:
        return False
    return False


def main():
    """主入口 - 桌面应用模式"""
    # 初始化
    ensure_directories()
    if not _bootstrap_api_setup():
        return
    check_config()
    if not ensure_dependencies():
        return
    _write_log("🚀 启动 Koto 桌面程序")

    # 设置 WebView2 持久化用户数据目录，使麦克风等权限在重启后保留
    _webview_data_dir = APP_ROOT / ".webview2_profile"
    _webview_data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(_webview_data_dir))
    _write_log(f"✔ WebView2 用户数据目录: {_webview_data_dir}")

    # 先启动后端线程，再导入 webview ——
    # 图标生成 + Flask 启动 + webview 导入 三者并行，大幅缩短启动时间
    server_info = start_flask_server() or {}

    # 打包端到端测试和无界面运维场景只需要 HTTP 服务。明确跳过
    # pywebview 初始化，避免无交互 Windows 会话阻塞桌面后端并掩盖
    # Flask 的真实启动状态。
    if os.environ.get("KOTO_SERVER_ONLY") == "1":
        _write_log("ℹ️ KOTO_SERVER_ONLY=1：仅运行 Flask 服务，不启动桌面窗口")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            _write_log("ℹ️ 收到停止信号，结束仅服务模式")
        return

    # 图标生成（仅首次运行需要；与 Flask 启动并行完成）
    _icon_ready = threading.Event()
    ico_path = ASSETS_DIR / "koto_icon.ico"
    png_path = ASSETS_DIR / "koto_icon.png"

    def _generate_icons():
        try:
            from PIL import Image, ImageDraw

            icon_dir = ASSETS_DIR
            icon_dir.mkdir(exist_ok=True, parents=True)
            if not png_path.exists():
                width, height = 256, 256
                image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle(
                    [0, 0, 256, 256], radius=56, fill=(79, 140, 255, 255)
                )
                draw.ellipse([48, 48, 208, 208], fill=(255, 255, 255, 255))
                draw.rectangle([72, 88, 184, 104], fill=(47, 107, 255, 255))
                draw.rectangle([72, 120, 184, 136], fill=(47, 107, 255, 255))
                draw.rectangle([72, 152, 184, 168], fill=(47, 107, 255, 255))
                image.save(str(png_path))
            if not ico_path.exists():
                image = Image.open(str(png_path))
                image.save(
                    str(ico_path),
                    sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)],
                )
        except Exception as e:
            _write_log(f"⚠️ 生成默认图标失败: {e}")
        finally:
            _icon_ready.set()

    _icon_thread = threading.Thread(target=_generate_icons, daemon=True)
    _icon_thread.start()

    # 在 Flask 后台启动的同时导入 webview（重叠 I/O 开销）
    import webview

    _write_log("✔ 已导入 webview")

    backend_app_url = f"http://{KOTO_HOST}:{KOTO_PORT}"
    health_url = f"{backend_app_url}/api/health"
    backend_ready = _wait_for_koto_health(
        health_url,
        STARTUP_FAST_READY_SEC,
        request_timeout=0.4,
        poll_interval=0.2,
    )
    app_url = backend_app_url

    if backend_ready:
        _write_log("✔ 后端健康检查已就绪")
    else:
        # Slow clean machines should see a live loading page instead of a false
        # 25-second failure. The page keeps polling and redirects when healthy.
        status_port = _find_available_port(KOTO_HOST, FALLBACK_PORT)
        if status_port is not None:
            status_url = f"http://{KOTO_HOST}:{status_port}"
            threading.Thread(
                target=_start_startup_status_server,
                kwargs={
                    "port": status_port,
                    "backend_url": backend_app_url,
                    "server_info": server_info,
                },
                name="KotoStartupStatus",
                daemon=True,
            ).start()
            if _wait_for_http_ok(
                status_url,
                2.0,
                request_timeout=0.25,
                poll_interval=0.1,
            ):
                app_url = status_url
                _write_log(
                    f"ℹ️ 后端仍在初始化，先显示启动状态页（最终目标 {backend_app_url}）"
                )
            else:
                _write_log("⚠️ 启动状态页未及时就绪，窗口直接等待后端")
        else:
            _write_log("⚠️ 没有可用端口显示启动状态页，窗口直接等待后端")

    # === 启动后台系统监控（守护线程，桌面模式专用）===
    try:
        from app.core.monitoring.system_event_monitor import get_system_event_monitor

        _sem = get_system_event_monitor(check_interval=60)  # 每 60 秒检查一次
        if not _sem.is_running():
            _sem.start()
            _write_log("✔ 系统资源监控已启动（CPU/内存/磁盘告警）")
    except Exception as _sem_err:
        _write_log(f"⚠️ 系统监控启动失败（非致命）: {_sem_err}")

    # === 预热本地路由模型（守护线程，不阻塞窗口创建）===
    def _init_local_router_async():
        import socket as _socket

        time.sleep(3)  # 等待 Flask 和 Ollama 完全就绪
        try:
            _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            _s.settimeout(0.5)
            _ollama_up = _s.connect_ex(("127.0.0.1", 11434)) == 0
            _s.close()
        except Exception:
            _ollama_up = False

        if not _ollama_up:
            _write_log(
                "🦙 Ollama 未运行，本地模型路由不可用（可运行 LocalModelInstaller 安装）"
            )
            return

        try:
            from app.core.routing.local_model_router import LocalModelRouter

            if LocalModelRouter.init_model():
                _write_log(f"🦙 本地路由模型已就绪: {LocalModelRouter._model_name}")
            else:
                _write_log(
                    "🦙 Ollama 运行中但无可用路由模型，请通过 LocalModelInstaller 下载模型"
                )
        except Exception as _lmr_e:
            _write_log(f"🦙 本地路由模型初始化跳过: {_lmr_e}")

    threading.Thread(target=_init_local_router_async, daemon=True).start()

    # 等待图标生成完成（通常此时已完成，因为与 Flask 等待并行进行）
    _icon_ready.wait(timeout=5)

    # 选择窗口图标（如存在）
    icon_path = None
    if ico_path.exists():
        icon_path = str(ico_path)

    # 检测屏幕分辨率，自动适配窗口大小（居中、占屏幕 88%）
    try:
        import ctypes as _ctypes

        _u32 = _ctypes.windll.user32
        _u32.SetProcessDPIAware()
        _screen_w = _u32.GetSystemMetrics(0)
        _screen_h = _u32.GetSystemMetrics(1)
        _win_w = max(1024, int(_screen_w * 0.65))
        _win_h = max(700, int(_screen_h * 0.65))
        _win_x = (_screen_w - _win_w) // 2
        _win_y = (_screen_h - _win_h) // 2
        _write_log(
            f"✔ 屏幕分辨率: {_screen_w}x{_screen_h}，初始窗口: {_win_w}x{_win_h} 位于 ({_win_x},{_win_y})"
        )
    except Exception as _e:
        _win_w, _win_h = 1200, 800
        _win_x, _win_y = None, None
        _write_log(f"⚠️ 无法检测屏幕分辨率，使用默认 1200x800: {_e}")

    # 创建桌面窗口
    window = webview.create_window(
        title="Koto - AI 个人助手",
        url=app_url,
        width=_win_w,
        height=_win_h,
        x=_win_x,
        y=_win_y,
        resizable=True,
        fullscreen=False,
        min_size=(400, 300),
        confirm_close=False,
        text_select=True,
        easy_drag=False,  # 关闭拖拽模式，防止拦截点击事件
        on_top=False,  # 不置顶，让用户正常使用
    )

    if icon_path:
        _write_log(f"✔ 图标路径: {icon_path}")
    _write_log(f"✔ 创建窗口，加载 {app_url}")

    if backend_ready and _backend_watchdog_enabled():
        _start_backend_health_watchdog(
            health_url,
            server_thread=server_info.get("thread"),
            expect_server_thread=bool(server_info.get("started")),
        )
        _write_log("✔ 后端健康守护已启动")
    elif backend_ready:
        _write_log("ℹ️ 后端健康守护默认关闭，避免任务流期间误判自恢复")
    elif _backend_watchdog_enabled():
        def _deferred_watchdog():
            if _wait_for_koto_health(
                health_url,
                STARTUP_HARD_TIMEOUT_SEC + 60.0,
                request_timeout=0.5,
                poll_interval=0.5,
            ):
                _start_backend_health_watchdog(
                    health_url,
                    server_thread=server_info.get("thread"),
                    expect_server_thread=bool(server_info.get("started")),
                )
                _write_log("✔ 延迟后端健康守护已启动")

        threading.Thread(
            target=_deferred_watchdog,
            name="KotoDeferredWatchdog",
            daemon=True,
        ).start()

    # 绑定窗口控制API
    window_api = WindowAPI(window, backend_app_url)
    window_api.full_size = (_win_w, _win_h)  # 同步实际初始窗口尺寸
    window.expose(window_api.switch_to_mini)
    window.expose(window_api.switch_to_full)
    window.expose(window_api.get_mode)
    window.expose(window_api.minimize)
    window.expose(window_api.maximize)
    window.expose(window_api.close)
    window.expose(window_api.force_close)
    window.expose(window_api.mark_file_modified)
    window.expose(window_api.open_url)

    # ── 原生窗口X按钮关闭拦截 ─────────────────────────────────────
    # 当用户点击操作系统原生的关闭按钮时，先让JS检查未保存文件；
    # 若有未保存文件，显示自定义对话框，取消本次关闭。
    # 对话框确认后调用 pywebview.api.force_close() 直接销毁窗口。
    import json as _json_mod
    import threading as _threading

    def _on_closing():
        if window_api._force_close_flag:
            # force_close() already set flag — allow
            return True

        # Fast path: Python-side mirror says no unsaved files → close immediately.
        # This avoids calling evaluate_js() from any thread (source of "未响应"):
        #   * Old approach: background thread → evaluate_js() → COM deadlock potential
        #   * New approach: JS keeps _unsaved_files dict in sync via mark_file_modified()
        if not window_api._unsaved_files:
            _request_app_shutdown("native_close")
            return True  # Allow close; no JS evaluation needed

        # There are unsaved files — show the WA dialog via background thread.
        # evaluate_js() is ONLY called when we actually need user confirmation.
        def _show_warn():
            try:
                unsaved = [
                    {"path": k, "name": v}
                    for k, v in list(window_api._unsaved_files.items())
                ]
                js_unsaved = _json_mod.dumps(unsaved)
                window.evaluate_js(
                    f"window.WA && window.WA.showCloseWarning && "
                    f"window.WA.showCloseWarning({js_unsaved}).then(function(d){{"
                    f'  if(d!=="cancel") window.pywebview.api.force_close();'
                    f"}})"
                )
            except Exception as _e:
                _write_log(f"⚠️ close-warning JS error: {_e}")
                # Fallback: force-close without saving
                window_api._force_close_flag = True
                _request_app_shutdown("close_warning_fallback")
                window.destroy()

        _threading.Thread(target=_show_warn, daemon=True).start()
        return False  # Cancel native close; thread handles the rest

    window.events.closing += _on_closing
    # ──────────────────────────────────────────────────────────────

    # 将 window_api 注入到 Flask app，供 HTTP 路由降级使用
    try:
        from web.app import app as _flask_app

        _flask_app.config["WINDOW_API"] = window_api
    except Exception as _e:
        _write_log(f"⚠️ 无法注入 window_api 到 Flask: {_e}")

    # 窗口引用（供托盘使用）
    window_ref = [window]

    # 创建系统托盘（在单独线程中）
    tray_icon = create_system_tray(window_ref)
    if tray_icon:
        tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
        tray_thread.start()
        _write_log("✔ 系统托盘线程已启动")

    # ── 启动阶段看门狗 ──────────────────────────────────
    # webview.start() 会永久阻塞主线程（这是正常行为，它就是窗口事件循环）。
    # 看门狗仅监控「窗口是否在超时内成功显示」，一旦 on_shown 触发就取消。
    # 避免之前的 bug：35秒后无条件 os._exit 杀掉正在正常运行的程序。
    _window_shown = threading.Event()

    def on_shown():
        """窗口显示后的回调"""
        _window_shown.set()  # 通知看门狗：窗口已加载
        _write_log("✔ 窗口已显示，应用正常运行中")
        _set_window_icon(icon_path)

    def _startup_watchdog(timeout_sec: int = 45):
        """启动看门狗：如果窗口在 timeout_sec 内未显示，记录诊断信息。
        注意：只记录日志 + thread dump，不强制退出。
        强制退出会导致用户看到"闪退"，不如让窗口继续尝试加载。"""
        if _window_shown.wait(timeout=timeout_sec):
            return  # 窗口正常显示，看门狗退出
        # 超时：窗口没有显示
        _write_log(f"⚠️ 窗口在 {timeout_sec} 秒内未显示，记录诊断信息")
        _dump_threads("startup-watchdog-timeout")
        # 不调用 os._exit()，让程序继续尝试

    watchdog = threading.Thread(target=_startup_watchdog, args=(45,), daemon=True)
    watchdog.start()

    _write_log("🚀 启动 webview.start（窗口事件循环）")

    # private_mode=False：关闭隐私模式，使麦克风等权限、Cookie 在重启后保留
    # storage_path：指定持久化用户数据目录（与前面创建的 .webview2_profile 一致）
    start_kwargs = {
        "func": on_shown,
        "debug": False,
        "private_mode": False,
        "storage_path": str(_webview_data_dir),
    }

    webview.start(**start_kwargs)
    _handle_webview_exit()


if __name__ == "__main__":
    main()
