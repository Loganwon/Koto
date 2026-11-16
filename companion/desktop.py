"""Local-only pywebview facade. API keys never appear in returned UI state."""

import os
import threading

from .contracts import CompanionError
from .model import ModelConfig
from .windows import WindowsDocuments, diagnose
from .workspace import LocalWorkspace
from .window_layout import FileDrawer
from .journal import EventJournal
from .file_actions import FileActions
from urllib.parse import urlsplit


class ClientUpgradeRequired(CompanionError):
    code = "client_upgrade_required"


class CompanionAPI:
    def __init__(
        self,
        config=None,
        documents=None,
        workspace=None,
        key_source="本次配置",
        journal=None,
    ):
        self._config = config
        self._config_lock = threading.Lock()
        self._documents = documents
        self._session = None
        self._workspace = workspace or LocalWorkspace()
        self._window = None
        self._key_source = key_source
        self._drawer = FileDrawer()
        self._journal = journal or EventJournal()

    def set_files_open(self, expanded):
        return self._result(lambda: self._drawer.set_open(self._window, bool(expanded)))

    def inspect_current(self, host="auto"):
        return self._result(
            lambda: self._get_session() and self._documents.read_current(host)
        )

    def _get_session(self):
        from .session import EditingSession

        with self._config_lock:
            if self._session is None:
                self._documents = self._documents or WindowsDocuments()
                self._session = EditingSession(
                    self._documents,
                    self._model,
                    lambda: self._workspace.session(
                        getattr(self._documents, "read_open_file", None)
                    ),
                    journal=self._journal,
                    file_actions=FileActions(self._workspace, self._documents),
                )
            return self._session

    def _model(self):
        from .agent import WorkspaceAgent

        with self._config_lock:
            config = self._config
        if not config:
            raise CompanionError("请先展开 API 设置，填写自己的接口和模型。")
        return WorkspaceAgent(config)

    def _editing_session(self):
        if getattr(self, "workflow_enabled", False):
            raise ClientUpgradeRequired(
                "侧栏已升级，请重新加载 Koto 后继续。原文与已完成文件保留。"
            )
        return self._get_session()

    def workspace_tree(self):
        return self._result(self._workspace.tree)

    def conversation_history(self, before=None, query="", limit=20):
        def read():
            session = self._get_session()
            if self._documents and hasattr(self._documents, "observation"):
                session.restore_history(self._documents.observation())
            return session.history_page(before, query, limit)

        return self._result(read)

    def choose_folder(self):
        def apply():
            if not self._window:
                raise CompanionError("请在桌面窗口中打开工作文件夹。")
            if self._session and self._session.snapshot()["busy"]:
                raise CompanionError("请先停止或等待当前任务完成，再切换文件夹。")
            import webview

            chosen = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            return self._workspace.open(chosen[0]) if chosen else self._workspace.tree()

        return self._result(apply)

    def open_workspace_file(self, file_id):
        def apply():
            path = self._workspace._path(file_id)
            if path.suffix.lower() not in {
                ".docx",
                ".xlsx",
                ".pptx",
                ".pdf",
                ".txt",
                ".md",
                ".csv",
                ".tsv",
                ".json",
            }:
                raise CompanionError("该格式暂不能从工作区打开。")
            os.startfile(str(path))

        return self._result(apply)

    def status(self):
        with self._config_lock:
            config, session = self._config, self._session
        observation = (
            self._documents.observation()
            if self._documents and hasattr(self._documents, "observation")
            else None
        )
        if session and observation:
            session.restore_history(observation)
        return {
            "environment": diagnose(),
            "observation": observation,
            "settings": {
                "configured": bool(config),
                "base_url": config.base_url if config else "https://api.deepseek.com",
                "model": config.model if config else "deepseek-chat",
                "provider": (
                    "DeepSeek"
                    if config
                    and urlsplit(config.base_url).hostname == "api.deepseek.com"
                    else (config.model if config else "")
                ),
                "key_source": self._key_source if config else "",
            },
            "session": (
                session.snapshot()
                if session
                else {
                    "phase": "idle",
                    "message": "在原生应用中选择文字，然后连接文档。",
                    "busy": False,
                }
            ),
        }

    @staticmethod
    def _result(call):
        try:
            value = call()
            return {"ok": True, "session": value}
        except CompanionError as error:
            return {
                "ok": False,
                "error": str(error),
                **({"code": error.code} if hasattr(error, "code") else {}),
            }
        except Exception as error:
            from .diagnostics import record_error

            return {
                "ok": False,
                "error": "操作未完成，请检查原生应用和连接状态。",
                "diagnostic_id": record_error(error),
            }

    def configure(self, base_url, model, api_key):
        def apply():
            if not all(isinstance(value, str) for value in (base_url, model, api_key)):
                raise CompanionError("API 配置需要是文字。")
            with self._config_lock:
                previous = self._config
                if (
                    not api_key.strip()
                    and previous
                    and previous.base_url.rstrip("/") != base_url.strip().rstrip("/")
                ):
                    raise CompanionError("更换 API 地址时，请重新填写对应服务的密钥。")
                config = ModelConfig(
                    base_url.strip(),
                    model.strip(),
                    api_key.strip() or (previous.api_key if previous else ""),
                ).validated()
                self._config = config
                if api_key.strip():
                    self._key_source = "本次输入"
            return None

        return self._result(apply)

    def connect(self, host):
        return self._result(lambda: self._editing_session().connect(host))

    def watch(self, host="auto", enabled=True):
        def apply():
            self._get_session()
            if hasattr(self._documents, "watch"):
                self._documents.watch(host, enabled)

        return self._result(apply)

    def submit(self, instruction, mode="auto", host="auto"):
        def apply():
            selected_host = host
            if mode not in ("edit", "read", "auto"):
                raise CompanionError("请选择修改文字或问文档。")
            if (
                not isinstance(instruction, str)
                or not instruction.strip()
                or len(instruction) > 10000
            ):
                raise CompanionError("请填写不超过 10000 字的要求。")
            session = self._editing_session()
            if session.snapshot()["busy"]:
                raise CompanionError("请先停止或等待当前任务完成。")
            self._model()  # Validate before replacing a previous review checkpoint.
            if mode == "auto":
                return session.submit(instruction, selected_host)
            if hasattr(self._documents, "read_current"):
                context = self._documents.read_current(selected_host)
                selected_host = context["host"]
            else:
                context = {}
                selected_host = "word" if selected_host == "auto" else selected_host
            if mode == "read":
                return session.ask(instruction, context)
            session.connect(selected_host, readable=mode == "auto")
            return session.start(instruction, agent=mode == "auto")

        return self._result(apply)

    def start(self, instruction):
        return self._result(lambda: self._editing_session().start(instruction))

    def advance(self, feedback=""):
        return self._result(lambda: self._editing_session().advance(feedback))

    def revise(self, feedback):
        return self._result(lambda: self._editing_session().revise(feedback))

    def stop(self):
        return self._result(lambda: self._get_session().stop())

    def retry(self):
        return self._result(lambda: self._editing_session().retry())

    def locate(self):
        return self._result(lambda: self._get_session().locate())

    def _close(self):
        if self._session:
            self._session.close()


def environment_config():
    key = os.environ.get("KOTO_COMPANION_API_KEY", "")
    if not key:
        return None
    return ModelConfig(
        os.environ.get("KOTO_COMPANION_BASE_URL", "https://api.deepseek.com"),
        os.environ.get("KOTO_COMPANION_MODEL", "deepseek-chat"),
        key,
    ).validated()
