"""Per-pane native RPC: editor objects never leave the Word/WPS add-in."""

from concurrent.futures import Future, TimeoutError
import copy
from queue import Queue, Empty
import threading
import time
import uuid

from .contracts import (
    CompanionError,
    DocumentConflict,
    DocumentTarget,
    Fragment,
    OperationCancelled,
    ResultUncertain,
    validate_replacement,
)
from .reading import TextSnapshot


class PaneDocuments:
    def __init__(self, host, timeout=20):
        self.host, self.timeout = host, timeout
        self.queue = Queue()
        self.pending = {}
        self.lock = threading.RLock()
        self.latest = {
            "connected": False,
            "watching": True,
            "message": "正在连接当前文档…",
        }
        self.closed = False
        self.live_reader = None
        self.last_error = None
        self.last_read = None
        self.delivery = {}

    def call(self, method, *args, permitted=None):
        command_id, future = uuid.uuid4().hex, Future()
        with self.lock:
            if self.closed:
                raise CompanionError("侧栏已断开，请重新打开。")
            self.pending[command_id] = (future, permitted)
            command = {"id": command_id, "method": method, "args": args}
            self.delivery[command_id] = {"command": command, "sent": 0}
            self.queue.put(command)
        try:
            return future.result(self.timeout)
        except TimeoutError:
            if not future.cancel() and method in (
                "replace",
                "replace_cell",
                "save_document",
                "export_pdf",
            ):
                raise ResultUncertain(
                    "宿主尚未确认写入结果，请检查文档；本次不会自动重试。"
                ) from None
            raise CompanionError("宿主响应超时，请回到文档后重试。") from None
        finally:
            with self.lock:
                self.pending.pop(command_id, None)
                self.delivery.pop(command_id, None)

    def poll(self):
        while True:
            with self.lock:
                # An unanswered poll may have been lost before the page saw it.
                # Only commands not acknowledged as started may be redelivered.
                retry = next(
                    (
                        entry
                        for key, entry in self.delivery.items()
                        if entry["sent"]
                        and time.monotonic() - entry["sent"] > 1
                        and key in self.pending
                        and not self.pending[key][0].running()
                        and not self.pending[key][0].done()
                    ),
                    None,
                )
                if retry:
                    retry["sent"] = time.monotonic()
                    return retry["command"]
            try:
                command = self.queue.get(timeout=0.3)
            except Empty:
                return None
            with self.lock:
                pending = self.pending.get(command["id"])
                if pending:
                    future, permitted = pending
                    if future.done():
                        continue
                    if permitted and not permitted():
                        future.set_exception(OperationCancelled("已停止，未写入文档。"))
                    else:
                        self.delivery[command["id"]]["sent"] = time.monotonic()
                        return command

    def begin(self, command_id):
        with self.lock:
            pending = self.pending.get(command_id)
            if not pending or pending[0].done() or self.closed:
                return False
            future, permitted = pending
            if permitted and not permitted():
                future.set_exception(OperationCancelled("已停止，未写入文档。"))
                return False
            return future.running() or future.set_running_or_notify_cancel()

    def reply(self, command_id, result=None, error=None):
        with self.lock:
            pending = self.pending.get(command_id)
            if not pending or pending[0].done():
                return
            if error:
                self.last_error = {
                    key: str(error.get(key, ""))[:100]
                    for key in ("method", "code", "location")
                }
                kind = {"conflict": DocumentConflict, "uncertain": ResultUncertain}.get(
                    error.get("kind"), CompanionError
                )
                pending[0].set_exception(
                    kind(str(error.get("message", "宿主操作未完成。"))[:500])
                )
            else:
                pending[0].set_result(result)

    def permitted(self, command_id):
        with self.lock:
            pending = self.pending.get(command_id)
            return bool(
                pending and not pending[0].done() and (not pending[1] or pending[1]())
            )

    def observe(self, value):
        if not isinstance(value, dict):
            raise CompanionError("宿主状态无效。")
        with self.lock:
            self.latest = {
                **value,
                "host": self.host,
                "checked_at": time.time(),
                "watching": True,
            }

    def observation(self):
        with self.lock:
            return copy.deepcopy(self.latest)

    def watch(self, host="auto", enabled=True):
        return None

    def bind_current(self, host="auto"):
        data = self.call("bind")
        data["fragments"] = tuple(
            Fragment(**fragment) for fragment in data["fragments"]
        )
        return DocumentTarget(**data)

    connect = bind_current
    connect_readable = bind_current

    def read(self, target, fragment):
        return self._text_result(self.call("read", target, fragment))

    def file_capabilities(self):
        return self.observation().get("file_operations", {})

    def _text_result(self, data):
        # Older panes and other hosts return a string. Updated WPS also reports
        # range coordinates for diagnosis, never as authority to retarget a write.
        self.last_read = None
        if isinstance(data, dict):
            binding = data.get("binding") or {}
            if isinstance(binding, dict):
                self.last_read = {
                    key: value
                    for key, value in binding.items()
                    if key in ("start", "end")
                    and type(value) is int
                    or key in ("fragment", "adapter", "scope_verification")
                    and isinstance(value, str)
                    and len(value) <= 100
                }
            data = data.get("text")
        if not isinstance(data, str):
            raise CompanionError("宿主没有返回有效的片段文字，已停止处理。")
        return data

    def replace(self, target, fragment, expected, text, permitted):
        validate_replacement(text)
        if not permitted():
            raise OperationCancelled("已停止，未写入文档。")
        return self._text_result(
            self.call("replace", target, fragment, expected, text, permitted=permitted)
        )

    def agent_context(self, target):
        return self.call("context", target)

    def replace_cell(self, target, fragment, expected, value_type, value, permitted):
        from .cell_edits import cell_proposal

        cell_proposal(value_type, value, "")
        if not permitted():
            raise OperationCancelled("已停止，未写入单元格。")
        return self.call(
            "replace_cell",
            target,
            fragment,
            expected,
            value_type,
            value,
            permitted=permitted,
        )

    def text_snapshot(self, target):
        data = self.call("snapshot", target)
        return TextSnapshot(
            data["name"],
            data["text"],
            tuple(data["coverage"]),
            tuple(data["limitations"]),
        )

    def read_current(self, host="auto"):
        return self.call("inspect")

    def read_open_file(self, path):
        return self.live_reader(path) if self.live_reader else None

    def locate(self, target, fragment):
        return self.call("locate", target, fragment)

    def close(self):
        with self.lock:
            self.closed = True
            for command_id, (future, _) in self.pending.items():
                if not future.done():
                    writing = future.running() and self.delivery[command_id]["command"][
                        "method"
                    ] in ("replace", "replace_cell", "save_document", "export_pdf")
                    future.set_exception(
                        ResultUncertain(
                            "侧栏断开，正在进行的修改尚未确认；请查看文档，不会自动重试。"
                        )
                        if writing
                        else OperationCancelled("侧栏已关闭。")
                    )
