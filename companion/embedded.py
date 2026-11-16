"""Loopback service for real Office/WPS task panes; no floating window."""

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import ssl
from urllib.parse import urlsplit, parse_qs

from .config import config_from_key_file
from .contracts import CompanionError
from .desktop import CompanionAPI, environment_config
from .workspace import LocalWorkspace
from .host_rpc import PaneDocuments
from .reading import TextSnapshot
from .requests import RequestCache
from .journal import default_journal


class FolderDialog:
    def create_file_dialog(self, _kind):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            folder = win32com.client.Dispatch("Shell.Application").BrowseForFolder(
                0, "选择 Koto 工作文件夹", 0x51
            )
            return [folder.Self.Path] if folder else None
        finally:
            pythoncom.CoUninitialize()


UI_VERSION = "20261025.1"


class EmbeddedAPI(CompanionAPI):
    def __init__(
        self,
        host,
        *,
        workflow_enabled=False,
        task_session_factory=None,
        state_dir=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.host = host
        self.workflow_requested = bool(workflow_enabled)
        self.workflow_enabled = self.workflow_requested and host in ("word", "wps")
        self.task_session_factory, self.state_dir = task_session_factory, state_dir
        self._window = FolderDialog()

    def _task_config(self):
        with self._config_lock:
            config = self._config
        if not config:
            raise CompanionError("请先在设置中连接模型。")
        return config

    def _get_session(self):
        if not self.workflow_enabled:
            return super()._get_session()
        with self._config_lock:
            if self._session is None:
                from .pane_task_session import PaneTaskSession

                self._session = (self.task_session_factory or PaneTaskSession)(
                    self._documents,
                    self._workspace,
                    self._task_config,
                    self._journal,
                    state_dir=self.state_dir,
                )
        return self._session

    def prepare_task(self, instruction, file_ids=(), previous_plan_id=None):
        return self._result(
            lambda: self._get_session().prepare(instruction, file_ids, previous_plan_id)
        )

    def execute_plan(self, plan_id):
        return self._result(lambda: self._get_session().execute(plan_id))

    def task_turn(self, message="", interaction="continue"):
        return self._result(lambda: self._get_session().turn_task(message, interaction))

    def open_delivery(self, name):
        return self._result(lambda: self._get_session().open_delivery(name))

    def adjust_plan(self, plan_id, file_name, new_format):
        return self._result(
            lambda: self._get_session().adjust_plan(plan_id, file_name, new_format)
        )

    def choose_folder(self):
        def choose():
            if self._session and self._session.snapshot()["busy"]:
                raise CompanionError("请先停止当前任务，再切换文件夹。")
            value = self._window.create_file_dialog(None)
            return self._workspace.open(value[0]) if value else self._workspace.tree()

        return self._result(choose)

    def set_files_open(self, expanded):
        return {"ok": True, "session": {"expanded": bool(expanded)}}

    def watch(self, host="auto", enabled=True):
        return super().watch(self.host, enabled)

    def connect(self, host="auto"):
        return super().connect(self.host)

    def inspect_current(self, host="auto"):
        return super().inspect_current(self.host)

    def submit(self, instruction, mode="auto", host="auto"):
        return super().submit(instruction, mode, self.host)

    def status(self):
        result = super().status()
        result["environment"].update(
            embedded=True, host=self.host, workflow_enabled=self.workflow_enabled
        )
        return result

    def fork(self, host, documents):
        return EmbeddedAPI(
            host,
            config=self._config,
            documents=documents,
            workspace=self._workspace,
            key_source=self._key_source,
            journal=self._journal,
            workflow_enabled=self.workflow_requested,
            task_session_factory=self.task_session_factory,
            state_dir=self.state_dir,
        )


PUBLIC_METHODS = frozenset(
    "status workspace_tree conversation_history choose_folder open_workspace_file set_files_open "
    "inspect_current configure connect watch submit start advance revise stop locate retry "
    "prepare_task execute_plan task_turn open_delivery adjust_plan".split()
)
HOSTS = ("word", "wps", "excel", "powerpoint")


class PaneServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, api, port=0, tls=None):
        self.api = api
        self.token = secrets.token_urlsafe(32)
        self.sessions = {}
        self.instances = {}
        self.requests = RequestCache()
        self.generation = secrets.token_hex(12)
        self.session_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), PaneHandler)
        if tls:
            self.socket = tls.wrap_socket(self.socket, server_side=True)
        self.origin = f"{'https' if tls else 'http'}://127.0.0.1:{self.server_port}"

    def read_open_file(self, path, owner):
        import os
        from urllib.parse import unquote

        def canonical(value):
            value = unquote(str(value))
            if urlsplit(value).scheme == "file":
                value = urlsplit(value).path
                if (
                    os.name == "nt"
                    and len(value) > 2
                    and value[0] == "/"
                    and value[2] == ":"
                ):
                    value = value[1:]
            return os.path.normcase(os.path.abspath(value))

        with self.session_lock:
            sessions = list(self.sessions.items())
        matches = [
            (key, api)
            for key, api in sessions
            if canonical(api._documents.observation().get("path", ""))
            == canonical(path)
        ]
        # A WPS pane can also read other documents open in its own application.
        matches += [
            (key, api)
            for key, api in sessions
            if key == owner and api.host == "wps" and (key, api) not in matches
        ]
        for _, api in matches[:8]:
            data = api._documents.call("read_file", str(path))
            if data:
                return TextSnapshot(
                    data["name"],
                    data["text"],
                    tuple(data["coverage"]),
                    tuple(data["limitations"]),
                )
        return None


class PaneHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Neither credentials nor document requests belong in access logs.

    def _allowed_origin(self):
        origin = self.headers.get("Origin")
        referer = self.headers.get("Referer")
        return (
            self.headers.get("Host") == urlsplit(self.server.origin).netloc
            and (not origin or origin == self.server.origin)
            and (not referer or referer.startswith(self.server.origin + "/"))
        )

    def _send(self, code, data, mime="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://appsforoffice.microsoft.com; style-src 'self' 'unsafe-inline'; connect-src 'self' https://appsforoffice.microsoft.com; frame-ancestors 'self' https://*.officeapps.live.com https://*.office.com; base-uri 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionError, OSError):
            pass  # A closed task pane must not produce noisy shutdown tracebacks.

    def do_GET(self):
        if not self._allowed_origin():
            return self._send(403, {"error": "origin"})
        route = urlsplit(self.path).path
        root = Path(__file__).parent
        if route == "/health":
            return self._send(200, {"service": "koto-embedded", "protocol": 1})
        if route == "/host/bootstrap":
            return self._send(
                200, {"token": self.server.token, "generation": self.server.generation}
            )
        if route in ("/ui/", "/ui/index.html"):
            host = parse_qs(urlsplit(self.path).query).get(
                "host", [self.server.api.host]
            )[0]
            if host not in HOSTS:
                return self._send(400, {"error": "host"})
            workflow = getattr(
                self.server.api, "workflow_requested", False
            ) and host in ("word", "wps")
            html = (
                root / ("ui/workflow.html" if workflow else "ui/legacy/index.html")
            ).read_text(encoding="utf-8")
            entry = "workflow.js" if workflow else "app.js"
            bootstrap = json.dumps(
                {
                    "token": self.server.token,
                    "host": host,
                    "generation": self.server.generation,
                }
            )
            sdk = (
                '<script src="https://appsforoffice.microsoft.com/lib/1/hosted/office.js"></script>'
                if host != "wps"
                else ""
            )
            html = html.replace(
                '<script src="' + entry + '"',
                sdk
                + "<script>window.KOTO_EMBEDDED="
                + bootstrap
                + ';</script><script src="office-common.js"></script><script src="word-host.js"></script><script src="excel-host.js"></script><script src="powerpoint-host.js"></script><script src="native-host.js"></script><script src="bridge.js"></script><script src="'
                + entry
                + '"',
            )
            # WPS can keep a pane renderer alive across service updates. A real
            # reload must fetch matching scripts instead of mixing build caches.
            for asset in (
                "app.js",
                "workflow.js",
                "task-flow.js",
                "bridge.js",
                "native-host.js",
                "office-common.js",
                "word-host.js",
                "excel-host.js",
                "powerpoint-host.js",
            ):
                html = html.replace(
                    'src="' + asset + '"', 'src="' + asset + "?v=" + UI_VERSION + '"'
                )
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        assets = {
            "/ui/app.js": ("ui/legacy/app.js", "application/javascript"),
            "/ui/history.js": ("ui/legacy/history.js", "application/javascript"),
            "/ui/style.css": ("ui/legacy/style.css", "text/css"),
            "/ui/workflow.js": ("ui/workflow.js", "application/javascript"),
            "/ui/task-flow.js": ("ui/task-flow.js", "application/javascript"),
            "/ui/workflow.css": ("ui/workflow.css", "text/css"),
            "/ui/bridge.js": ("addins/bridge.js", "application/javascript"),
            "/ui/native-host.js": ("addins/native-host.js", "application/javascript"),
            "/ui/word-host.js": ("addins/word/host.js", "application/javascript"),
            "/ui/excel-host.js": ("addins/excel/host.js", "application/javascript"),
            "/ui/powerpoint-host.js": (
                "addins/powerpoint/host.js",
                "application/javascript",
            ),
            "/ui/office-common.js": (
                "addins/office-common.js",
                "application/javascript",
            ),
            "/icon.png": ("addins/icon.png", "image/png"),
            "/wps/main.js": ("addins/wps/main.js", "application/javascript"),
            "/wps/ribbon.xml": ("addins/wps/ribbon.xml", "application/xml"),
            "/wps/index.html": ("addins/wps/loader.html", "text/html"),
            "/wps/": ("addins/wps/loader.html", "text/html"),
        }
        if route in assets:
            path, mime = assets[route]
            return self._send(200, (root / path).read_bytes(), mime + "; charset=utf-8")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        token = self.headers.get("X-Koto-Token", "")
        authorized = self._allowed_origin() and hmac.compare_digest(
            token, self.server.token
        )
        # Drain a bounded body before closing, including rejected requests.
        # Otherwise Windows may reset the connection before the client sees 403.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2 * 1024 * 1024:
                return self._send(400 if authorized else 403, {"error": "request"})
            previous_timeout = self.connection.gettimeout()
            try:
                self.connection.settimeout(3)
                raw = self.rfile.read(length)
            finally:
                self.connection.settimeout(previous_timeout)
        except (ValueError, OSError):
            return self._send(400 if authorized else 403, {"error": "request"})
        if not authorized:
            return self._send(403, {"error": "unauthorized"})
        try:
            args = json.loads(raw)
            if not isinstance(args, list) or len(args) > 4:
                raise ValueError()
            if self.path == "/host/connections":
                with self.server.session_lock:
                    values = [
                        {
                            "channel": key,
                            "host": api.host,
                            "connected": api._documents.observation().get(
                                "connected", False
                            ),
                            "error": api._documents.last_error,
                            "phase": (
                                api._session.snapshot()["phase"]
                                if api._session
                                else "idle"
                            ),
                        }
                        for key, api in self.server.sessions.items()
                    ]
                return self._send(200, values)
            if self.path == "/host/attach":
                host = args[0]
                if host not in HOSTS:
                    raise ValueError()
                instance = args[1] if len(args) > 1 else secrets.token_urlsafe(24)
                if not isinstance(instance, str) or not 1 <= len(instance) <= 100:
                    raise ValueError()
                with self.server.session_lock:
                    channel = self.server.instances.get((host, instance))
                    if not channel or channel not in self.server.sessions:
                        documents = PaneDocuments(host)
                        channel = secrets.token_urlsafe(24)
                        documents.live_reader = lambda path: self.server.read_open_file(
                            path, channel
                        )
                        self.server.sessions[channel] = self.server.api.fork(
                            host, documents
                        )
                        self.server.instances[(host, instance)] = channel
                return self._send(
                    200, {"channel": channel, "generation": self.server.generation}
                )
            channel = self.headers.get("X-Koto-Channel", "")
            api = self.server.sessions.get(channel)
            if self.path.startswith("/host/"):
                if api is None:
                    return self._send(403, {"error": "channel"})
                operation = self.path.removeprefix("/host/")
                documents = api._documents
                if operation == "poll":
                    result = documents.poll()
                elif operation == "begin":
                    result = documents.begin(*args)
                elif operation == "reply":
                    result = documents.reply(*args)
                elif operation == "observe":
                    result = documents.observe(*args)
                elif operation == "permit":
                    result = documents.permitted(*args)
                elif operation == "detach":
                    api._close()
                    with self.server.session_lock:
                        self.server.sessions.pop(channel, None)
                    result = None
                else:
                    return self._send(404, {"error": "not found"})
            else:
                method = self.path.removeprefix("/api/")
                if not self.path.startswith("/api/") or method not in PUBLIC_METHODS:
                    return self._send(404, {"error": "not found"})
                if api is None:
                    return self._send(403, {"error": "channel"})
                request_id = self.headers.get("X-Koto-Request", "")
                order = int(self.headers.get("X-Koto-Sequence", "0"))
                action = lambda: self.server.requests.ordered(
                    channel, method, order, lambda: getattr(api, method)(*args)
                )
                result = (
                    self.server.requests.run(
                        (channel, request_id),
                        (method, json.dumps(args, sort_keys=True)),
                        action,
                    )
                    if request_id and method != "status"
                    else action()
                )
        except (ValueError, TypeError):
            return self._send(400, {"ok": False, "error": "请求参数无效。"})
        except Exception:
            return self._send(500, {"ok": False, "error": "宿主连接暂时不可用。"})
        self._send(200, result)


def main():
    parser = argparse.ArgumentParser(description="Koto embedded add-in backend")
    parser.add_argument("--host", choices=HOSTS)
    parser.add_argument("--port", type=int)
    parser.add_argument("--api-key-file")
    parser.add_argument("--workspace")
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument("--settings")
    parser.add_argument(
        "--workflow", action=argparse.BooleanOptionalAction, default=None
    )
    args = parser.parse_args()
    if args.settings:
        settings = json.loads(Path(args.settings).read_text(encoding="utf-8-sig"))
        for name in (
            "host",
            "port",
            "api_key_file",
            "workspace",
            "tls_cert",
            "tls_key",
            "workflow",
        ):
            if getattr(args, name) is None and name in settings:
                setattr(args, name, settings[name])
    args.host = args.host or "wps"
    args.port = args.port or 0
    config = (
        config_from_key_file(args.api_key_file)
        if args.api_key_file
        else environment_config()
    )
    workspace = LocalWorkspace(
        excluded=[args.api_key_file] if args.api_key_file else []
    )
    if args.workspace:
        workspace.open(args.workspace)
    api = EmbeddedAPI(
        args.host,
        config=config,
        documents=PaneDocuments(args.host),
        workspace=workspace,
        key_source=Path(args.api_key_file).name if args.api_key_file else "环境变量",
        journal=default_journal(),
        workflow_enabled=args.workflow is not False,
    )
    tls = None
    if args.tls_cert and args.tls_key:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.tls_cert, args.tls_key)
    server = PaneServer(api, args.port, tls)
    # The host reads one handshake line; no API key or document contents.
    if __import__("sys").stdout:
        print(
            json.dumps(
                {"url": server.origin + "/ui/", "pid": __import__("os").getpid()}
            ),
            flush=True,
        )
    try:
        server.serve_forever()
    finally:
        api._close()
        server.server_close()


if __name__ == "__main__":
    main()
