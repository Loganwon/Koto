"""One-click WPS entry: start the local service, then open its existing pane.

Uses WPS's published wpsjsrpcsdk single-process protocol (1.1.31). This
launcher has no file-open or document-edit command and does not replay tasks.
"""

import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx

PROJECT = Path(__file__).resolve().parents[2]
RELAY = "http://127.0.0.1:58890"


def settings_path():
    return Path(os.environ["LOCALAPPDATA"]) / "Koto/Addin/host.json"


def service_ready(client, origin):
    try:
        response = client.get(origin + "/health")
        return response.status_code == 200 and response.json() == {
            "service": "koto-embedded",
            "protocol": 1,
        }
    except (httpx.HTTPError, ValueError):
        return False


def ensure_service(settings_file):
    settings = json.loads(settings_file.read_text(encoding="utf-8-sig"))
    port = int(settings.get("port", 19742))
    if not 1 <= port <= 65535:
        raise ValueError("本机服务端口无效。")
    tls = settings.get("tls_cert")
    origin = f"{'https' if tls else 'http'}://127.0.0.1:{port}"
    with httpx.Client(verify=tls or True, trust_env=False, timeout=1) as client:
        if service_ready(client, origin):
            return origin
        python = Path(
            settings.get("runtime_python")
            or PROJECT / ".venv-agent/Scripts/pythonw.exe"
        )
        if not python.is_file():
            raise RuntimeError(
                "Koto Agent 运行环境尚未安装，请重新运行 companion/addins/install.ps1。"
            )
        subprocess.Popen(
            [
                str(python),
                str(PROJECT / "companion/addins/service.py"),
                "--settings",
                str(settings_file),
            ],
            cwd=PROJECT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if service_ready(client, origin):
                return origin
            time.sleep(0.2)
    raise RuntimeError("Koto 本机服务未能启动，请重新运行安装脚本。")


def open_request(request_id, refresh=False):
    # Match the SDK's echo callback. All executable text is a fixed Koto
    # entry point; no document text, credentials, paths or user input enter it.
    callback = (
        "var xhr = new XMLHttpRequest();xhr.open('POST', '"
        + RELAY
        + "/transferEcho/runParams');xhr.send(JSON.stringify({id: '"
        + request_id
        + "', response: res}));"
    )
    # The fixed expression also works with an older already-loaded add-in entry.
    # TaskPane.Navigate reloads this pane; it cannot open or edit a document.
    entry = (
        "OpenKoto"
        if not refresh
        else (
            "(function(){if(typeof kotoPane!=='undefined'&&kotoPane){"
            "kotoPane.Navigate(location.origin+'/ui/?host=wps&build=20261025.1');"
            "kotoPane.Visible=true;return true;}return OpenKoto();})"
        )
    )
    start = {
        "name": "Koto",
        "function": "var res = " + entry,
        "info": "{});" + callback + "void(0",
        "showToFront": True,
        "jsPluginsXml": "",
    }
    data = base64.b64encode(json.dumps(start).encode()).decode()
    return {
        "id": request_id,
        "app": "wps",
        "mode": False,
        "timeout": 45000,
        "data": "ksowebstartupwps://" + data,
    }


def open_pane(origin, refresh=False):
    # This is the documented WPS relay startup protocol, not a new WPS file.
    with httpx.Client(
        trust_env=False,
        timeout=2,
        headers={"Origin": origin, "Referer": origin + "/"},
    ) as client:
        try:
            client.post(RELAY + "/version", json={}).raise_for_status()
        except httpx.HTTPError:
            os.startfile("ksoWPSCloudSvr://start=RelayHttpServer")
            deadline = time.monotonic() + 8
            while True:
                try:
                    client.post(RELAY + "/version", json={}).raise_for_status()
                    break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("无法连接 WPS，请先安装并打开 WPS 文字。")
                    time.sleep(0.3)
        # A fixed entry action only. A timeout never causes another invocation.
        response = client.post(
            RELAY + "/transfer/runParams",
            json=open_request(str(uuid.uuid4()), refresh),
            timeout=55,
        )
        response.raise_for_status()
        if response.text.strip() not in ("true", "1"):
            raise RuntimeError("WPS 未确认 Koto 已打开，请检查 WPS 的加载项提示。")


@contextmanager
def entry_lock(folder):
    import msvcrt

    with (folder / "entry.lock").open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-only", action="store_true")
    parser.add_argument("--refresh-ui", action="store_true")
    args = parser.parse_args()
    path = settings_path()
    try:
        with entry_lock(path.parent) as acquired:
            if acquired:
                origin = ensure_service(path)
                if not args.service_only:
                    open_pane(origin, args.refresh_ui)
    except Exception as error:
        # A stable local diagnostic; never include API credentials or documents.
        message = (
            str(error)
            if isinstance(error, RuntimeError)
            else (
                "Koto 未能打开。请检查 WPS 加载项授权提示；如服务未启动，请重新运行安装脚本。"
            )
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "entry-status.txt").write_text(message, encoding="utf-8")
        if not args.service_only:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "Koto", 0x40)
        return 1
    (path.parent / "entry-status.txt").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
