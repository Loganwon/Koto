"""Process-wide single-instance ownership for the Koto desktop window."""

from __future__ import annotations

import os
import sys
from typing import Callable

MUTEX_NAME = r"Local\KotoMainWindowMutex_v2"
WINDOW_TITLE = "Koto - AI 个人助手"
_mutex_handle: int | None = None


def _activate_existing_window() -> None:
    """Best-effort activation of the existing Koto window on Windows."""
    try:
        import win32gui

        def _visit(hwnd: int, _extra: object) -> bool:
            title = win32gui.GetWindowText(hwnd)
            if title != WINDOW_TITLE:
                return True
            try:
                win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return False

        win32gui.EnumWindows(_visit, None)
    except Exception:
        pass


def acquire_desktop_instance(
    *,
    log: Callable[[str], None] | None = None,
    activate_existing: bool = True,
) -> bool:
    """Acquire Koto's per-user desktop mutex.

    The function is process-idempotent so ``koto_setup`` and ``koto_app`` can
    both call it while sharing one authoritative mutex implementation.
    """
    global _mutex_handle

    if os.environ.get("KOTO_SERVER_ONLY") == "1" or sys.platform != "win32":
        return True
    if _mutex_handle is not None:
        return True

    emit = log or (lambda _message: None)
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if not handle:
            emit("⚠️ 无法创建桌面单实例锁，继续启动")
            return True

        error_already_exists = 183
        if kernel32.GetLastError() == error_already_exists:
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            emit("ℹ️ Koto 桌面实例已在运行，本次启动将激活现有窗口")
            if activate_existing:
                _activate_existing_window()
            return False

        # Keep the handle alive for the lifetime of the desktop process.
        _mutex_handle = int(handle)
        return True
    except Exception as exc:
        emit(f"⚠️ 桌面单实例锁初始化失败（非致命）: {exc}")
        return True


def release_desktop_instance() -> None:
    """Release the mutex immediately before an intentional process handoff."""
    global _mutex_handle

    handle = _mutex_handle
    if handle is None or sys.platform != "win32":
        return
    _mutex_handle = None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        try:
            kernel32.ReleaseMutex(handle)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        # Process exit is the final ownership cleanup fallback.
        pass
