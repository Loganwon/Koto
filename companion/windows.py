"""Word/WPS live ranges owned by one COM STA; never edits files on disk."""

from concurrent.futures import Future, TimeoutError
from queue import Empty, Queue
import sys
import threading
import uuid

from .observation import DocumentObservation, capture_document, capture_selection
from .native_reading import NativeReading

from .contracts import (
    CompanionError,
    DocumentConflict,
    DocumentTarget,
    Fragment,
    OperationCancelled,
    ResultUncertain,
    validate_replacement,
)

HOSTS = {"word": ("Word", "Word.Application"), "wps": ("WPS 文字", "kwps.Application")}


def diagnose() -> dict:
    result = {"platform": sys.platform, "hosts": []}
    if sys.platform != "win32":
        result["message"] = "当前版本提供 Windows 原生连接器；Mac 连接器尚未实现。"
        return result
    import winreg

    for host, (label, progid) in HOSTS.items():
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID"):
                registered = True
        except FileNotFoundError:
            registered = False
        result["hosts"].append({"id": host, "name": label, "installed": registered})
    return result


class WindowsDocuments(DocumentObservation, NativeReading):
    """All COM calls, including test factories, run on the same apartment."""

    def __init__(self, application_factory=None, timeout: float = 20):
        self._factory = application_factory
        self._timeout = timeout
        self._queue = Queue()
        self._ready = threading.Event()
        self._startup_error = None
        self._closed = False
        self._observation_lock = threading.Lock()
        self._observation = {
            "watching": True,
            "connected": False,
            "message": "正在寻找打开的文档…",
            "revision": 0,
        }
        self._thread = threading.Thread(
            target=self._serve, name="CompanionCOM", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(10):
            raise CompanionError("原生连接器启动超时。")
        if self._startup_error:
            raise CompanionError(self._startup_error)

    def _serve(self):
        try:
            if sys.platform != "win32":
                raise CompanionError("当前版本的原生文字连接器仅支持 Windows。")
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            self._startup_error = "无法启动原生连接器，请在 Windows 安装 pywin32。"
            self._ready.set()
            return
        self._application = None
        self._document = None
        self._target_id = None
        self._ranges = {}
        self._applications = {}
        self._watch_host, self._watch_enabled = "auto", True
        self._last_host, self._next_observation = None, 0
        self._ready.set()
        try:
            while True:
                pythoncom.PumpWaitingMessages()
                try:
                    command = self._queue.get(timeout=0.05)
                except Empty:
                    try:
                        self._poll_observation()
                    except Exception:
                        # Observation is read-only and must never break editing commands.
                        pass
                    continue
                if command is None:
                    break
                operation, args, future = command
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(getattr(self, "_" + operation)(*args))
                except CompanionError as error:
                    # Do not transport traceback frames containing COM objects
                    # into a different apartment via Future.result().
                    future.set_exception(type(error)(str(error)))
                except Exception:
                    future.set_exception(
                        CompanionError(
                            "原生应用未响应或文档已关闭，请回到文档检查后重新连接。"
                        )
                    )
        finally:
            self._ranges.clear()
            self._document = None
            self._application = None
            self._applications.clear()
            pythoncom.CoUninitialize()

    def _call(self, operation, *args):
        if self._closed:
            raise CompanionError("原生连接器已关闭。")
        future = Future()
        self._queue.put((operation, args, future))
        try:
            return future.result(timeout=self._timeout)
        except TimeoutError:
            if future.cancel():
                raise CompanionError("原生应用繁忙，操作未开始，请稍后重试。") from None
            raise ResultUncertain(
                "原生应用仍在处理，结果待核实。请先检查文档，不要重复提交修改。"
            ) from None

    def connect(self, host):
        return self._call("connect", host)

    def connect_readable(self, host):
        return self._call("connect", host, True)

    def bind_current(self, host="auto"):
        return self._call("bind_current", host)

    def _bind_current(self, host):
        if host == "auto":
            if self._watch_enabled or not self._last_host:
                self._next_observation = 0
                self._poll_observation()
            observed = self.observation()
            if not observed.get("connected"):
                raise CompanionError(observed.get("message", "请先打开文档。"))
            host = observed["host"]
        return self._connect(host, True, True)

    def read(self, target_id, fragment_id):
        return self._call("read", target_id, fragment_id)

    def replace(self, target_id, fragment_id, expected, replacement, permitted):
        validate_replacement(replacement)
        return self._call(
            "replace", target_id, fragment_id, expected, replacement, permitted
        )

    def locate(self, target_id, fragment_id):
        return self._call("locate", target_id, fragment_id)

    def close(self):
        if not self._closed:
            self._closed = True
            self._queue.put(None)
            if threading.current_thread() is not self._thread:
                self._thread.join(timeout=2)

    @staticmethod
    def _guard_range(native_range):
        # A paragraph inside one cell is safe; never replace structural cell marks.
        if "\x07" in native_range.Text or (
            native_range.Tables.Count and native_range.Cells.Count > 1
        ):
            raise CompanionError("这一段跨越了单元格边界，请选择单个单元格内的文字。")
        for collection in (
            "Fields",
            "InlineShapes",
            "Hyperlinks",
            "ContentControls",
        ):
            if getattr(native_range, collection).Count:
                raise CompanionError(
                    "这一段包含域、图片或受控内容，可以先用“问文档”读取和分析。"
                )
        for attribute in (
            "Bold",
            "Italic",
            "Underline",
            "Size",
            "Color",
            "Hidden",
            "StrikeThrough",
        ):
            if getattr(native_range.Font, attribute) == 9999999:
                raise CompanionError(
                    "这一段包含混合字符格式，请选择格式一致的较小片段。"
                )
        if not native_range.Font.Name:
            # WPS returns an empty Name for ordinary Chinese/Latin fallback.
            # Uniform per-script fonts are safe; genuine mixed fonts still
            # return an empty/undefined value within at least one script.
            try:
                scripts = [
                    getattr(native_range.Font, name)
                    for name in ("NameAscii", "NameFarEast", "NameOther", "NameBi")
                ]
            except Exception:
                scripts = []
            if not scripts or not all(
                isinstance(name, str) and name for name in scripts
            ):
                raise CompanionError("这一段包含混合字体，请缩小选区后重试。")

    def _connect(self, host, readable=False, quick=False):
        if host not in HOSTS:
            raise CompanionError("请选择 Word 或 WPS 文字。")
        if self._factory:
            application = self._factory(host)
        else:
            import win32com.client

            try:
                application = win32com.client.GetActiveObject(HOSTS[host][1])
            except Exception:
                raise CompanionError(
                    f"请先打开 {HOSTS[host][0]} 和需要编辑的文档。"
                ) from None
        document = application.ActiveDocument
        self._applications[host] = application
        self._last_host = host
        protected = bool(document.ReadOnly or document.ProtectionType != -1)
        if protected and not readable:
            raise CompanionError("该文档只读或受保护，请先在原生应用中解除限制。")
        selected = application.Selection.Range.Duplicate
        if selected.StoryType != 1:
            raise CompanionError("本轮仅支持正文，请在正文中选择文字。")
        scope = "已选文字"
        if selected.Start == selected.End:
            selected = selected.Paragraphs.Item(1).Range.Duplicate
            scope = "光标所在段落"
        context = (capture_selection if quick else capture_document)(
            host, document, selected
        )
        ranges, fragments = {}, []
        for index in range(1, min(selected.Paragraphs.Count, 51) + 1):
            paragraph = selected.Paragraphs.Item(index).Range
            part = document.Range(
                max(paragraph.Start, selected.Start), min(paragraph.End, selected.End)
            )
            while part.End > part.Start and part.Text[-1:] in ("\r", "\x07"):
                part.End -= 1
            if not part.Text.strip():
                continue
            if len(fragments) >= 50 or len(part.Text) > 8000:
                raise CompanionError("选区过大，请每次选择不超过 50 段的普通正文。")
            reason = "文档只读或受保护" if protected else ""
            try:
                self._guard_range(part)
            except CompanionError as error:
                if not readable:
                    raise
                reason = str(error)
            fragment_id = uuid.uuid4().hex
            ranges[fragment_id] = part.Duplicate
            label = "正文"
            if part.Tables.Count and part.Cells.Count:
                cell = part.Cells.Item(1)
                label = f"第 {cell.RowIndex} 行，第 {cell.ColumnIndex} 列"
            fragments.append(
                Fragment(fragment_id, part.Text, label, not reason, reason)
            )
        if selected.Paragraphs.Count > 50:
            raise CompanionError("选区超过 50 段，请缩小范围。")
        if not fragments:
            raise CompanionError("没有可处理的文字，请先选择正文段落。")
        self._application, self._document = application, document
        self._target_id, self._ranges = uuid.uuid4().hex, ranges
        self._target_host = host
        return DocumentTarget(
            self._target_id,
            host,
            document.Name,
            scope,
            tuple(fragments),
            document.FullName if document.Path else "",
            context,
        )

    def _get_range(self, target_id, fragment_id, writable=False):
        if target_id != self._target_id or fragment_id not in self._ranges:
            raise DocumentConflict("文档绑定已变化，请重新读取选区。")
        if writable and (
            self._document.ReadOnly or self._document.ProtectionType != -1
        ):
            raise CompanionError("文档已变为只读或受保护。")
        # Access the pinned document, never whichever window is currently active.
        _ = self._document.Name
        return self._ranges[fragment_id]

    def _read(self, target_id, fragment_id):
        return self._get_range(target_id, fragment_id).Text

    def _replace(self, target_id, fragment_id, expected, replacement, permitted):
        part = self._get_range(target_id, fragment_id, writable=True)
        self._guard_range(part)
        if part.Text != expected:
            raise DocumentConflict(
                "这一段在等待期间被修改了。请检查文档并重新读取选区，避免覆盖你的输入。"
            )
        if not permitted():
            raise OperationCancelled("已停止，未执行这一段的修改。")
        # One host call updates only the selected text, without its paragraph mark.
        try:
            part.Text = replacement
            actual = part.Text
        except Exception:
            raise ResultUncertain(
                "原生写入结果待核实，请先检查文档，不会自动重试。"
            ) from None
        if actual != replacement:
            raise ResultUncertain(
                "原生文档的读回内容与修改不同，请检查文档后重新连接。"
            )
        return actual

    def _locate(self, target_id, fragment_id):
        part = self._get_range(target_id, fragment_id)
        self._document.Activate()
        part.Select()
