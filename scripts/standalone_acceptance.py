"""Run isolated, offline acceptance against production Flask and Kernel code.

The provider is a deterministic fixture. File tools, document persistence,
frontend actions, task ledger, HTTP routes and UI bundles remain production code.
No user document or model credential is used. Start with the venv Python:

    python scripts/standalone_acceptance.py --serve
    python scripts/standalone_acceptance.py --http-only
    python scripts/standalone_acceptance.py --render-shell

Browser checks can open the printed loopback URL and use the displayed fixture
instructions. The fixture provider responds to the explicit Chinese commands
below; it is not a replacement product model.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ORIGINAL = "我们希望通过这个项目，把团队的工作效率进行一个全面的提升。"
REPLACEMENT = "本项目旨在提升团队工作效率。"


def configure_isolation(state_dir: Path) -> Path:
    """Set every mutable runtime owner before importing application modules."""
    state_dir.mkdir(parents=True, exist_ok=True)
    workspace = state_dir / "workspace"
    workspace.mkdir(exist_ok=True)
    data = state_dir / "runtime-data"
    data.mkdir(exist_ok=True)
    env = {
        "KOTO_DEPLOY_MODE": "local",
        "KOTO_AUTH_ENABLED": "false",
        "KOTO_SKIP_BACKGROUND_RUNTIME": "true",
        "KOTO_RUNTIME_DATA_DIR": str(data),
        "KOTO_DB_DIR": str(data / "db"),
        "KOTO_WORKSPACE_DIR": str(workspace),
        "KOTO_USER_SETTINGS_PATH": str(state_dir / "user_settings.json"),
        "KOTO_DEEPSEEK_CONFIG_PATH": str(state_dir / "fixture.env"),
        "DEEPSEEK_API_KEY": "acceptance-fixture-not-a-real-key",
        "DEEPSEEK_BASE_URL": "http://127.0.0.1:1/fixture-never-contacted",
        "KOTO_DEEPSEEK_MODEL": "acceptance-fixture",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
    }
    file_stores = {
        "KOTO_ADDON_AUDIT_DB_PATH": "addon_audit.sqlite",
        "KOTO_ADDON_REGISTRY_PATH": "addons.json",
        "KOTO_FILE_TASK_SUMMARY_PATH": "file_task_summaries.json",
        "KOTO_FILE_TASK_PLAN_PATH": "file_task_plans.json",
        "KOTO_FILE_TASK_FOLLOWUP_PATH": "file_task_followups.json",
        "KOTO_KB_CONFIG_PATH": "kb_config.json",
        "KOTO_CALENDAR_EVENTS_PATH": "calendar_events.json",
        "KOTO_REMINDERS_PATH": "reminders.json",
        "KOTO_SCHEDULED_TASKS_PATH": "scheduled_tasks.json",
        "KOTO_RATING_DB_PATH": "ratings.db",
        "KOTO_SHADOW_OBSERVATIONS_PATH": "shadow_observations.json",
        "KOTO_FILE_INDEX_PATH": "file_index.json",
        "KOTO_TOKEN_USAGE_PATH": "token_usage.json",
        "KOTO_PROACTIVE_QUEUE_PATH": "proactive_queue.json",
        "KOTO_TRIGGERS_PATH": "triggers.json",
        "KOTO_FILE_NETWORK_DB_PATH": "processed_file_network.db",
        "KOTO_MEMORY_PATH": "memory.json",
        "KOTO_USERS_FILE": "users.json",
        "KOTO_ACTIVATION_CODES_FILE": "activation_codes.json",
        "KOTO_JWT_SECRET_FILE": "jwt_secret.txt",
        "KOTO_WORK_FILE_LIBRARY_DB_PATH": "work_file_library.db",
        "KOTO_AUDIT_DB_PATH": "audit.db",
    }
    env.update({key: str(data / filename) for key, filename in file_stores.items()})
    env["KOTO_RAG_INDEX_DIR"] = str(data / "rag-index")
    os.environ.update(env)
    (state_dir / "fixture.env").write_text("# Offline acceptance only\n", encoding="utf-8")
    settings = {
        "storage": {
            "workspace_dir": str(workspace),
            "documents_dir": str(workspace / "documents"),
            "images_dir": str(workspace / "images"),
            "chats_dir": str(workspace / "chats"),
        },
        "appearance": {"theme": "light", "language": "zh-CN", "ui_zoom": 1.0},
        "ai": {
            "default_model": "auto", "use_local_only": False,
            "deepseek_model": "acceptance-fixture", "cloud_model": "acceptance-fixture",
            "show_thinking": False, "show_task_type": False, "auto_save_files": False,
        },
        "proxy": {"enabled": False, "auto_detect": False, "manual_proxy": ""},
    }
    (state_dir / "user_settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    create_fixtures(workspace)
    return workspace


def create_fixtures(workspace: Path) -> None:
    from docx import Document

    (workspace / "季度材料.txt").write_text(
        "季度营收240万元，同比增长20%。增长原因有待进一步分析。\n", encoding="utf-8"
    )
    (workspace / "修改验收.txt").write_text(ORIGINAL + "\n第二段保持不变。\n", encoding="utf-8")
    doc = Document()
    doc.add_heading("Koto 原版独立工作台验收", 0)
    doc.add_paragraph(ORIGINAL)
    doc.add_paragraph("第二段保持不变。")
    doc.save(workspace / "项目协作方案.docx")
    # Additional visual/roundtrip fixture. It is synthetic and independent of
    # the existing minimal acceptance document and all user-owned documents.
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE

    rich = Document()
    rich.add_heading("办公格式与精确修改样例", level=1)
    paragraph = rich.add_paragraph()
    paragraph.add_run(ORIGINAL).bold = True
    rich.add_paragraph("跨段起点：保留本段样式。")
    rich.add_paragraph("跨段终点：仅做显式替换。")
    rich.add_paragraph("清单待确认", style="List Bullet")
    rich.add_paragraph("第二条保持不变：中文、α、🚀。", style="List Bullet")
    table = rich.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "项目", "状态"
    table.cell(1, 0).text, table.cell(1, 1).text = "市场预算40万元", "预算待确认"
    link_paragraph = rich.add_paragraph("参考链接：")
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rich.part.relate_to("https://example.com/koto", RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Koto固定样例链接"
    run.append(text)
    link.append(run)
    link_paragraph._p.append(link)
    rich.sections[0].header.paragraphs[0].text = "固定样例页眉：保留"
    rich.save(workspace / "办公格式样例.docx")


@dataclass
class FixtureProvider:
    workspace: Path
    calls: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    active_streams: int = 0

    @staticmethod
    def _messages(prompt: Any) -> list[dict[str, Any]]:
        return list(prompt) if isinstance(prompt, (list, tuple)) else [
            {"role": "user", "content": str(prompt or "")}
        ]

    @staticmethod
    def _value(message: dict[str, Any]) -> Any:
        raw = message.get("content", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return raw
        return payload.get("value", payload) if isinstance(payload, dict) else payload

    @staticmethod
    def _tool(name: str, args: dict[str, Any], suffix: str) -> dict[str, Any]:
        return {"content": "", "tool_calls": [{"id": "fixture-" + suffix,
                "name": name, "args": args}]}

    def _response(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=0)
        user = str(messages[last_user].get("content", ""))
        tools = [m for m in messages[last_user + 1:] if m.get("role") == "tool"]
        names = []
        for m in messages[last_user + 1:]:
            for call in m.get("tool_calls", []) or []:
                names.append(str(call.get("name") or (call.get("function") or {}).get("name") or ""))
        if "验收生成" in user:
            if not tools:
                return self._tool("read_file", {"file_path": str(self.workspace / "季度材料.txt")}, "read-material")
            if "write_file" not in names:
                observed = str(self._value(tools[-1]))
                content = "# 季度分析报告\n\n来源：季度材料.txt\n\n" + observed + "\n"
                return self._tool("write_file", {
                    "file_path": str(self.workspace / "季度分析报告.md"), "content": content,
                }, "write-report")
            observed = str(self._value(tools[-1]))
            return {"content": "报告已写入季度分析报告.md。执行回执：" + observed, "tool_calls": []}
        if "验收读取" in user:
            if not tools:
                return self._tool("read_file", {"file_path": str(self.workspace / "季度材料.txt")}, "read-only")
            return {"content": "已读取材料。实际工具内容：" + str(self._value(tools[-1])), "tool_calls": []}
        if any(word in user for word in ("验收修改", "验收冲突", "验收保存失败", "验收格式修改", "验收表格", "验收列表", "验收跨段")):
            if not tools:
                return self._tool("ui_read_context", {}, "ui-read")
            value = self._value(tools[-1])
            if not isinstance(value, dict):
                return {"content": "工具没有返回可用文档状态，未继续修改。", "tool_calls": []}
            if value.get("success") is False or value.get("ok") is False or value.get("error"):
                return {"content": "操作未完成，保留现有文档。真实错误：" + json.dumps(value, ensure_ascii=False), "tool_calls": []}
            if "ui_apply_edit" not in names:
                revision = str(value.get("revision") or value.get("revision_after") or "")
                if "验收冲突" in user:
                    revision = "deliberately-stale-fixture-revision"
                anchor, replacement = ORIGINAL, REPLACEMENT
                if "验收表格" in user:
                    anchor, replacement = "预算待确认", "预算已复核"
                elif "验收列表" in user:
                    anchor, replacement = "清单待确认", "清单已确认"
                elif "验收跨段" in user:
                    anchor = "跨段起点：保留本段样式。\n跨段终点：仅做显式替换。"
                    replacement = "跨段起点：已复核。\n跨段终点：已明确。"
                logical_operation = hashlib.sha256((anchor + "\0" + replacement).encode("utf-8")).hexdigest()[:12]
                return self._tool("ui_apply_edit", {
                    "expected_revision": revision, "anchor_text": anchor,
                    "replacement": replacement, "operation_id": "edit-" + revision + "-" + logical_operation,
                }, "ui-edit")
            if "ui_save" not in names:
                revision = str(value.get("revision_after") or value.get("revision") or "")
                return self._tool("ui_save", {
                    "expected_revision": revision,
                    "expected_source_sha256": str(value.get("source_sha256") or ""),
                    "operation_id": "save-" + revision,
                }, "ui-save")
            return {"content": "文档操作已取得实际保存回执：" + json.dumps(value, ensure_ascii=False), "tool_calls": []}
        if "验收失败" in user:
            raise RuntimeError("Deterministic provider failure for acceptance")
        if "验收取消" in user or "验收恢复" in user:
            return {"content": "这是一段用于取消和恢复验收的持续输出。" * 30, "tool_calls": [], "_slow": True}
        return {"content": "你好，Koto 已通过逐块输出验收。", "tool_calls": []}

    def generate_content(self, prompt: Any = "", model: str = "", *, stream: bool = False,
                         system_instruction: str = "", **_kwargs: Any) -> Any:
        messages = self._messages(prompt)
        response = self._response(messages)
        with self._lock:
            self.calls.append({"model": model, "stream": bool(stream),
                "message_count": len(messages), "system_context_present": bool(system_instruction),
                "tool_names": [c["name"] for c in response.get("tool_calls", [])]})
        if not stream:
            return response

        def chunks() -> Iterator[dict[str, Any]]:
            with self._lock:
                self.active_streams += 1
            try:
                text = str(response.get("content") or "")
                accumulated = ""
                width = 5 if not response.get("_slow") else 4
                for start in range(0, len(text), width):
                    piece = text[start:start + width]
                    accumulated += piece
                    yield {"delta": piece, "content": accumulated, "tool_calls": []}
                    time.sleep(0.09 if not response.get("_slow") else 0.12)
                yield {"delta": "", "content": accumulated,
                       "tool_calls": response.get("tool_calls", []), "stream_final": True,
                       "model": model or "acceptance-fixture"}
            finally:
                with self._lock:
                    self.active_streams -= 1

        return chunks()

    def list_models(self) -> list[Any]:
        return []


def build_app(state_dir: Path):
    workspace = configure_isolation(state_dir)
    provider = FixtureProvider(workspace)
    import app.core.llm.provider_factory as providers
    providers.get_llm_provider = lambda *_args, **_kwargs: provider
    # Keep all FileService backups inside the isolated acceptance workspace.
    from app.core.agent.toolkits.builtin.file_editor_plugin import FileEditorPlugin
    original_init = FileEditorPlugin.__init__
    FileEditorPlugin.__init__ = lambda self, workspace_dir=None: original_init(
        self, workspace_dir or str(workspace)
    )
    import web.app as webapp
    import web.blueprints.workspace_assistant as workspace_routes
    from app.core.agent import frontend_observability

    # These legacy UI caches still have project-relative defaults. Override
    # them before the first request so fixture opens/cleanup never touch the
    # user's workspace tmp files or supervision log.
    workspace_routes._TMP_DIR = workspace / "tmp"
    workspace_routes._TMP_ROOT = workspace / "tmp"
    webapp.UPLOAD_DIR = str(state_dir / "uploads")
    Path(webapp.UPLOAD_DIR).mkdir(exist_ok=True)
    frontend_observability._event_log_path = lambda: state_dir / "frontend-observability.jsonl"
    from app.core.agent.factory import _build_registry
    from app.core.agent.kernel_agent import KernelAgent
    import app.core.agent.kernel_agent_service as agent_service
    from flask import jsonify, redirect, request

    agent = KernelAgent(provider, _build_registry(), model_id="acceptance-fixture",
        enable_pii_filter=False, enable_output_validation=False,
        use_tool_router=False, allow_model_fallback=False)
    agent_service.get_kernel_agent = lambda **_kwargs: agent
    webapp.API_KEY = "acceptance-fixture-not-a-real-key"
    webapp._start_memory_extraction = lambda *_args, **_kwargs: None
    webapp._get_writing_style_instruction = lambda *_args, **_kwargs: ""
    webapp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    webapp.app.config["ACCEPTANCE_FIXTURE"] = True
    controls = {"fail_saves": False}

    @webapp.app.before_request
    def fixture_failures():
        if controls["fail_saves"] and request.path == "/api/v1/workspace/auto_save":
            return jsonify({"ok": False, "error": "Acceptance fixture: simulated persistence failure"}), 507

    @webapp.app.get("/__acceptance/status")
    def fixture_status():
        return jsonify({"fixture_provider": True, "workspace": str(workspace),
            "state_dir": str(state_dir), "calls": provider.calls,
            "controls": controls, "files": sorted(p.name for p in workspace.iterdir() if p.is_file()),
            "commands": ["验收流式", "验收读取", "验收生成", "验收修改", "验收格式修改", "验收表格", "验收列表", "验收跨段", "验收冲突",
                         "验收保存失败", "验收失败", "验收取消", "验收恢复"]})

    @webapp.app.get("/__acceptance")
    def fixture_controls_page():
        from html import escape

        status = "开启" if controls["fail_saves"] else "关闭"
        return ("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
            "<title>Koto 离线验收控制</title><body style='font:16px system-ui;max-width:800px;margin:40px auto;line-height:1.7'>"
            "<h1>Koto 离线验收控制</h1><p>此服务使用测试模型。Flask、Kernel、文档工具与界面为实际生产代码。</p>"
            "<p><a href='/'>打开原版工作台</a> · <a href='/__acceptance/status'>查看验收状态</a></p>"
            "<p>隔离工作区：<code>" + escape(str(workspace)) + "</code></p>"
            "<p>打开“项目协作方案.docx”，发送“验收修改”；其他命令：验收流式、验收读取、验收生成、验收冲突、验收失败、验收取消、验收恢复。</p>"
            "<p>打开“办公格式样例.docx”，可发送验收格式修改、验收表格、验收列表、验收跨段；用于观察真实编辑与保存回执，不代表真实模型质量。</p>"
            "<p>模拟保存故障：<strong>" + status + "</strong></p>"
            "<form method=post action='/__acceptance/control'><button name=fail_saves value=true>开启保存故障</button> "
            "<button name=fail_saves value=false>关闭保存故障</button> "
            "<button name=reset_fixtures value=true>重置隔离文档</button></form>"
            "<p>重置只影响测试工作区；重置后请在工作台重新打开文档，以获得当前文件版本。</p></body></html>")

    @webapp.app.post("/__acceptance/control")
    def fixture_control():
        is_form = bool(request.form)
        body = request.form if is_form else request.get_json(silent=True) or {}
        if "fail_saves" in body:
            controls["fail_saves"] = str(body["fail_saves"]).lower() in {"true", "1", "yes"}
        if str(body.get("reset_fixtures", "")).lower() in {"true", "1", "yes"}:
            create_fixtures(workspace)
        if is_form:
            return redirect("/__acceptance")
        return jsonify({"ok": True, "controls": controls})

    return webapp.app, provider, workspace


def parse_sse(raw: str) -> list[dict[str, Any]]:
    events = []
    for frame in raw.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
        if not data:
            continue
        try:
            events.append(json.loads(data))
        except ValueError:
            continue
    return events


def render_offline_shell(output: Path) -> Path:
    """Render actual Jinja and bundles for local-file layout inspection only.

    API calls are not mocked or made to look successful. Consequently this
    artifact cannot demonstrate model, server, edit/save or recovery behavior.
    """
    from flask import Flask, render_template

    renderer = Flask("koto_offline_layout", template_folder=str(ROOT / "web" / "templates"))
    static = (ROOT / "web" / "static").resolve()

    def file_asset(filename: str) -> str:
        target = (static / filename).resolve()
        if static != target and static not in target.parents:
            raise ValueError("Static asset escapes the production asset directory")
        if not target.is_file():
            raise FileNotFoundError(f"Production asset is missing: {target}")
        return target.as_uri()

    with renderer.test_request_context("/"):
        markup = render_template("index.html", initial_theme="light",
            asset_url=file_asset, csrf_token=lambda: "offline-layout-only")
    markup = markup.replace("<head>", "<head>\n<!-- Static layout inspection only; no backend or model is simulated. -->\n"
        '<meta name="koto-acceptance-mode" content="static-layout-only">', 1)
    markup = markup.replace("<title>", "<title>[仅界面核验] ", 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markup, encoding="utf-8")
    return output


def http_acceptance(app, provider: FixtureProvider, workspace: Path) -> dict[str, Any]:
    """Exercise actual request handlers, Kernel and file effects via Flask client."""
    checks = []
    with app.test_client() as client:
        for command in ("验收流式", "验收读取", "验收生成", "验收失败"):
            response = client.post("/api/chat/stream", json={
                "session": "acceptance-" + command, "message": command,
                "locked_task": "AGENT", "locked_model": "cloud",
            }, buffered=False)
            assert response.status_code == 200, (command, response.status_code)
            events = []
            live_delta_seen = False
            for part in response.response:
                part_events = parse_sse(part.decode("utf-8") if isinstance(part, bytes) else str(part))
                if any(e.get("type") == "message.delta" for e in part_events):
                    live_delta_seen = live_delta_seen or provider.active_streams > 0
                events.extend(part_events)
            response.close()
            assert events, command
            encoded = json.dumps(events, ensure_ascii=False)
            if command == "验收失败":
                assert "failed" in encoded or "error" in encoded, encoded
                checks.append("provider failure yields an explicit failed result")
            elif command == "验收生成":
                report = workspace / "季度分析报告.md"
                assert report.is_file(), encoded
                assert "240万元" in report.read_text(encoding="utf-8"), encoded
                checks.append("production Kernel read/write tools create a report containing observed source data")
            elif command == "验收读取":
                assert "240万元" in encoded, encoded
                checks.append("production Kernel returns actual source file content")
            else:
                deltas = [e for e in events if e.get("type") == "message.delta"]
                assert len(deltas) > 1, encoded
                assert live_delta_seen, "Agent buffered all text until the provider ended"
                checks.append("actual Agent HTTP stream emits multiple incremental message events")
            if command == "验收生成":
                identity = next(e for e in events if e.get("type") == "run.started")
                task_id, run_id = identity["task_id"], identity["run_id"]
                journal = client.get(f"/api/tasks/{task_id}/events", query_string={"run_id": run_id}).get_json()
                durable = journal["data"]
                sequences = [e["seq"] for e in durable]
                assert sequences == list(range(1, len(durable) + 1)), sequences
                assert sum(e["type"] == "run.finished" for e in durable) == 1, durable
                calls_before = len(provider.calls)
                cursor = max(1, len(durable) // 2)
                replay = client.get(f"/api/tasks/{task_id}/stream", query_string={
                    "run_id": run_id, "after_seq": cursor, "timeout": 1,
                })
                replayed = parse_sse(replay.get_data(as_text=True))
                facts = [e for e in replayed if int(e.get("seq") or 0) > 0]
                assert facts and [e["seq"] for e in facts] == sequences[cursor:], facts
                assert len(provider.calls) == calls_before, "Replay re-executed the model or write tool"
                checks.append("durable event cursors replay the same run without re-running tools or model")
        cancellation = client.post("/api/chat/stream", json={
            "session": "acceptance-cancel", "message": "验收取消",
            "locked_task": "AGENT", "locked_model": "cloud",
        }, buffered=False)
        cancelled_events = []
        cancel_result: dict[str, Any] = {}
        cancel_task_id = ""
        stop_sent = False
        for part in cancellation.response:
            part_events = parse_sse(part.decode("utf-8") if isinstance(part, bytes) else str(part))
            cancelled_events.extend(part_events)
            for event in part_events:
                cancel_task_id = str(event.get("task_id") or cancel_task_id)
                if event.get("type") == "message.delta" and not stop_sent:
                    stop_sent = True

                    def request_stop():
                        with app.test_client() as stop_client:
                            stopped = stop_client.post(f"/api/tasks/{cancel_task_id}/cancel", json={})
                            cancel_result.update(status=stopped.status_code, body=stopped.get_json())

                    stopper = threading.Thread(target=request_stop)
                    stopper.start()
                    stopper.join(timeout=5)
                    assert not stopper.is_alive()
        cancellation.close()
        assert stop_sent and cancel_result.get("status") in (200, 202), cancel_result
        terminal = [e for e in cancelled_events if e.get("type") == "run.finished"]
        assert len(terminal) == 1, cancelled_events
        final_state = str(terminal[0].get("state") or terminal[0].get("status")
                          or terminal[0].get("payload", {}).get("status") or "")
        assert final_state == "cancelled", terminal
        assert provider.active_streams == 0, "Cancellation did not close the provider iterator"
        checks.append("cancel request stops the actual model stream and reaches one confirmed cancelled terminal")
        opened = client.post("/api/v1/workspace/open_file_by_path", json={"path": "项目协作方案.docx"})
        data = opened.get_json()
        assert opened.status_code == 200 and data.get("file_type") == "docx", data
        saved = client.post("/api/v1/workspace/auto_save", json={
            "file_type": "docx", "file_id": data["file_id"],
            "ws_source_path": "项目协作方案.docx", "explicit": True,
            "data": "<h1>Koto 原版独立工作台验收</h1><p>" + REPLACEMENT + "</p><p>第二段保持不变。</p>",
        })
        assert saved.status_code == 200 and saved.get_json().get("src_written"), saved.get_json()
        from docx import Document
        actual = "\n".join(p.text for p in Document(workspace / "项目协作方案.docx").paragraphs)
        assert REPLACEMENT in actual and ORIGINAL not in actual, actual
        checks.append("production DOCX open/save handlers persist a document verified by independent python-docx readback")
        client.post("/__acceptance/control", json={"fail_saves": True})
        failed = client.post("/api/v1/workspace/auto_save", json={
            "file_type": "docx", "file_id": data["file_id"], "explicit": True,
            "ws_source_path": "项目协作方案.docx", "data": "<p>Must not be committed</p>",
        })
        assert failed.status_code == 507
        unchanged = "\n".join(p.text for p in Document(workspace / "项目协作方案.docx").paragraphs)
        assert unchanged == actual
        checks.append("injected persistence failure leaves the actual DOCX unchanged")
        client.post("/__acceptance/control", json={"fail_saves": False, "reset_fixtures": True})
    return {"mode": "production-flask-kernel-fixture-provider", "passed": checks,
            "provider_calls": len(provider.calls), "browser_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--http-only", action="store_true")
    parser.add_argument("--render-shell", action="store_true")
    args = parser.parse_args()
    base = ROOT / "build" / "standalone-acceptance"
    base.mkdir(parents=True, exist_ok=True)
    if args.render_shell:
        output = render_offline_shell(base / "offline-shell.html")
        print(json.dumps({"rendered": str(output), "url": output.as_uri(),
            "mode": "static-layout-only", "backend_verified": False,
            "model_verified": False}, ensure_ascii=False), flush=True)
        return
    state = (args.state_dir or Path(tempfile.mkdtemp(prefix="run-", dir=base))).resolve()
    app, provider, workspace = build_app(state)
    if args.http_only:
        result = http_acceptance(app, provider, workspace)
        (state / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({**result, "state_dir": str(state)}, ensure_ascii=False), flush=True)
    if args.serve or not args.http_only:
        from werkzeug.serving import make_server
        server = make_server("127.0.0.1", args.port, app, threaded=True)
        url = f"http://127.0.0.1:{server.server_port}"
        (state / "server.json").write_text(json.dumps({"url": url, "workspace": str(workspace),
            "fixture_provider": True}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ready": True, "url": url, "workspace": str(workspace),
            "state_dir": str(state), "fixture_provider": True}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
