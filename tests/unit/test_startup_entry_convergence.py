from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def test_all_human_facing_launchers_converge_on_desktop_setup() -> None:
    powershell = (ROOT / "Koto_Start.ps1").read_text(encoding="utf-8-sig")
    legacy_batch = (ROOT / "start_koto.bat").read_text(encoding="utf-8-sig")
    entrypoints = json.loads(
        (ROOT / "config" / "runtime_entrypoints.json").read_text(encoding="utf-8")
    )

    assert entrypoints["desktop"] == "src/koto_setup.py"
    assert entrypoints["policy"]["allow_fallback"] is False
    assert "runtime_entrypoints.json" in powershell
    assert "$candidates" not in powershell
    assert 'set "MODE=desktop"' in legacy_batch
    assert 'call "%~dp0Koto_Start.bat" "%MODE%"' in legacy_batch
    assert "-m web.app" not in legacy_batch


def test_packaged_desktop_includes_shared_single_instance_runtime() -> None:
    spec = (ROOT / "koto.spec").read_text(encoding="utf-8-sig")

    assert "'src.single_instance'" in spec
    assert "'src.startup_events'" in spec


def test_every_process_recovery_releases_the_shared_mutex() -> None:
    desktop = (ROOT / "src" / "koto_app.py").read_text(encoding="utf-8-sig")

    release_calls = desktop.count(
        "\n    _release_desktop_instance_lock()"
    ) + desktop.count("\n        _release_desktop_instance_lock()")
    assert release_calls == 3
    assert desktop.count("os.execve(") == 3


def test_desktop_port_has_one_runtime_authority() -> None:
    powershell = (ROOT / "Koto_Start.ps1").read_text(encoding="utf-8-sig")
    port_step = powershell.split("# Step 6: 端口检查", 1)[1].split("# Step 7:", 1)[0]

    assert 'if ($Mode -eq "desktop")' in port_step
    assert "$KOTO_PORT" in port_step
    assert "Resolve-PortConflict" in port_step


def test_single_instance_mutex_is_process_idempotent(monkeypatch) -> None:
    from src import single_instance

    calls = {"create": 0}

    class Kernel32:
        def CreateMutexW(self, *_args):
            calls["create"] += 1
            return 123

        @staticmethod
        def GetLastError():
            return 0

    monkeypatch.setattr(single_instance.sys, "platform", "win32")
    monkeypatch.setattr(single_instance, "_mutex_handle", None)
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=Kernel32()), raising=False
    )

    assert single_instance.acquire_desktop_instance() is True
    assert single_instance.acquire_desktop_instance() is True
    assert calls["create"] == 1


def test_single_instance_rejects_a_second_process(monkeypatch) -> None:
    from src import single_instance

    closed: list[int] = []

    class Kernel32:
        @staticmethod
        def CreateMutexW(*_args):
            return 456

        @staticmethod
        def GetLastError():
            return 183

        @staticmethod
        def CloseHandle(handle):
            closed.append(handle)

    monkeypatch.setattr(single_instance.sys, "platform", "win32")
    monkeypatch.setattr(single_instance, "_mutex_handle", None)
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=Kernel32()), raising=False
    )

    assert single_instance.acquire_desktop_instance(activate_existing=False) is False
    assert closed == [456]


def test_single_instance_activates_only_the_real_koto_window(monkeypatch) -> None:
    from src import single_instance

    shown: list[tuple[int, int]] = []
    foreground: list[int] = []
    titles = {
        10: "Koto documentation - Browser",
        20: single_instance.WINDOW_TITLE,
        30: "Another window",
    }
    fake_win32gui = SimpleNamespace(
        EnumWindows=lambda callback, extra: [callback(hwnd, extra) for hwnd in titles],
        GetWindowText=lambda hwnd: titles[hwnd],
        ShowWindow=lambda hwnd, command: shown.append((hwnd, command)),
        SetForegroundWindow=foreground.append,
    )
    monkeypatch.setitem(sys.modules, "win32gui", fake_win32gui)

    single_instance._activate_existing_window()

    assert shown == [(20, 9)]
    assert foreground == [20]


def test_single_instance_can_release_for_an_intentional_restart(monkeypatch) -> None:
    from src import single_instance

    released: list[int] = []
    closed: list[int] = []

    kernel32 = SimpleNamespace(
        ReleaseMutex=released.append,
        CloseHandle=closed.append,
    )
    monkeypatch.setattr(single_instance.sys, "platform", "win32")
    monkeypatch.setattr(single_instance, "_mutex_handle", 789)
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False
    )

    single_instance.release_desktop_instance()

    assert released == [789]
    assert closed == [789]
    assert single_instance._mutex_handle is None
