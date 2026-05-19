import json
import sys
from types import SimpleNamespace

import pytest

from app.core.agent import file_task_capability
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_planner import FileTaskPlannerRegistry, FileTaskPlannerSupport, HermesPlannerAdapter
from app.core.agent.file_task_runtime import FileTaskRuntime
from app.core.agent.tool_design_protocol import TOOL_DESIGN_PROTOCOL


class FakePlannerAdapter:
    def __init__(self, backend_name="hermes", *, available=True, responses=None, reason="planner unavailable"):
        self.backend_name = backend_name
        self._available = available
        self._responses = list(responses or [{"content": "planner response", "tool_calls": []}])
        self._reason = reason
        self.calls = []

    def support(self, request=None):
        return FileTaskPlannerSupport(
            backend=self.backend_name,
            available=self._available,
            detected=True,
            reason="" if self._available else self._reason,
            repo_path=f".tmp_external_agents/{self.backend_name}",
            transport="test",
            transport_hint="test adapter",
        )

    def call(self, *, request, messages, system, tools):
        if not self._available:
            raise RuntimeError(self._reason)
        self.calls.append(
            {
                "task": request.task,
                "message_count": len(messages),
                "tool_names": [tool.get("name") for tool in tools],
            }
        )
        if len(self._responses) == 1:
            return self._responses[0]
        return self._responses.pop(0)


class TrackingFileTaskModelClient(FileTaskModelClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cloud_calls = 0

    def _call_cloud(self, *, request, messages, system, tools):
        self.cloud_calls += 1
        return {"content": "cloud fallback", "tool_calls": []}


def test_file_task_request_from_mapping_promotes_external_planner_fields_into_options():
    request = FileTaskRequest.from_mapping(
        {
            "task": "总结文档",
            "planner_backend": "hermes",
            "planner_policy": "prefer_hermes",
            "planner_command": ["python", "planner_bridge.py"],
            "planner_timeout": 42,
            "planner_allow_native_fallback": True,
            "planner_options": {"transport": "stdin_json"},
        }
    )

    assert request.options["planner_backend"] == "hermes"
    assert request.options["planner_policy"] == "prefer_hermes"
    assert request.options["planner_command"] == ["python", "planner_bridge.py"]
    assert request.options["planner_timeout"] == 42
    assert request.options["planner_allow_native_fallback"] is True
    assert request.options["planner_options"] == {"transport": "stdin_json"}


def test_file_task_model_client_uses_explicit_external_planner_backend():
    planner = FakePlannerAdapter(
        responses=[{"content": "planner response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(task="总结文档", options={"planner_backend": "hermes"})

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "planner response"
    assert response["_planner"]["backend"] == "hermes"
    assert response["_planner"]["policy"] == "explicit_backend"
    assert response["_planner"]["source"] == "external"
    assert client.cloud_calls == 0
    assert planner.calls == [
        {
            "task": "总结文档",
            "message_count": 1,
            "tool_names": ["parse_file_to_text"],
        }
    ]


def test_file_task_model_client_falls_back_to_native_when_explicit_planner_allows_it():
    planner = FakePlannerAdapter(available=False, reason="planner bridge missing")
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="总结文档",
        options={
            "planner_backend": "hermes",
            "planner_allow_native_fallback": True,
        },
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["fallback_from"] == "hermes"
    assert client.cloud_calls == 1


def test_file_task_model_client_prefers_external_backend_from_policy():
    planner = FakePlannerAdapter(
        responses=[{"content": "planner policy response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(task="总结文档", options={"planner_policy": "prefer_hermes"})

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "planner policy response"
    assert response["_planner"]["backend"] == "hermes"
    assert response["_planner"]["policy"] == "prefer_hermes"
    assert client.cloud_calls == 0
    assert planner.calls[0]["tool_names"] == ["parse_file_to_text"]


def test_supported_planner_policies_only_advertise_backup_helper_modes():
    assert file_task_capability.supported_planner_policies() == [
        "auto",
        "native_only",
        "hermes_fallback",
        "openclaw_fallback",
    ]


def test_file_task_model_client_uses_external_fallback_policy_when_native_fails():
    planner = FakePlannerAdapter(
        responses=[{"content": "external fallback response", "tool_calls": []}],
    )

    class FailingNativeClient(FileTaskModelClient):
        def _call_cloud(self, *, request, messages, system, tools):
            raise RuntimeError("cloud unavailable")

        def _is_local_available(self) -> bool:
            return False

    client = FailingNativeClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(task="总结文档", options={"planner_policy": "hermes_fallback"})

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "external fallback response"
    assert response["_planner"]["backend"] == "hermes"
    assert response["_planner"]["fallback_from"] == "native"
    assert planner.calls == [
        {
            "task": "总结文档",
            "message_count": 1,
            "tool_names": [],
        }
    ]


def test_file_task_model_client_falls_back_to_local_when_cloud_call_fails():
    class CloudThenLocalClient(FileTaskModelClient):
        def __init__(self):
            super().__init__()
            self.cloud_calls = 0
            self.local_calls = []

        def _call_cloud(self, *, request, messages, system, tools):
            self.cloud_calls += 1
            raise RuntimeError("cloud unavailable")

        def _call_local(self, *, request, messages, system, tools):
            self.local_calls.append(
                {
                    "request": request,
                    "messages": messages,
                    "system": system,
                    "tools": tools,
                }
            )
            return {"content": "local fallback", "tool_calls": []}

        def _is_local_available(self) -> bool:
            return True

    client = CloudThenLocalClient()
    request = FileTaskRequest(
        task="总结当前 Word 文档",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        options={"planner_policy": "native_only"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "local fallback"
    assert response["_planner"] == {
        "backend": "native",
        "transport": "native",
        "policy": "native_only",
        "source": "native",
        "reason": "requested_policy",
    }
    assert client.cloud_calls == 1
    assert client.local_calls == [
        {
            "request": request,
            "messages": [{"role": "user", "content": "总结"}],
            "system": "system prompt",
            "tools": [{"name": "parse_file_to_text"}],
        }
    ]


def test_file_task_model_client_auto_policy_stays_native_for_supported_docx_task():
    planner = FakePlannerAdapter(
        responses=[{"content": "planner policy response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="总结当前 Word 文档",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["policy"] == "native_only"
    assert client.cloud_calls == 1
    assert planner.calls == []


def test_file_task_model_client_auto_policy_prefers_hermes_for_unsupported_file_type():
    planner = FakePlannerAdapter(
        responses=[{"content": "planner auto response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="读取这个 CAD 文件并整理修改方案",
        files=[],
        current_file=None,
        target_path="drawing.dwg",
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "分析 CAD 文件"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["policy"] == "hermes_fallback"
    assert response["_planner"]["reason"] == "unsupported_file_types:dwg"
    assert client.cloud_calls == 1
    assert planner.calls == []


def test_file_task_model_client_auto_policy_prefers_hermes_for_js_file_without_native_workflow():
    planner = FakePlannerAdapter(
        responses=[{"content": "planner auto response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="修改这个 js 文件并整理变更方案",
        target_path="app.js",
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "分析 JS 文件"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["policy"] == "hermes_fallback"
    assert response["_planner"]["reason"] == "unsupported_file_types:js"
    assert client.cloud_calls == 1
    assert planner.calls == []


def test_file_task_model_client_auto_policy_keeps_txt_file_on_native_path():
    planner = FakePlannerAdapter(
        responses=[{"content": "planner auto response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="润色当前 txt 文件并直接写回",
        current_file=FileTaskFile(path="notes.txt", name="notes.txt", type="text", target=True),
        target_path="notes.txt",
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "润色 TXT 文件"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["policy"] == "native_only"
    assert response["_planner"]["reason"] == "covered_by_koto_native"
    assert client.cloud_calls == 1
    assert planner.calls == []


def test_file_task_model_client_auto_policy_prefers_hermes_for_browser_style_task():
    planner = FakePlannerAdapter(
        responses=[{"content": "browser planner response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="访问 https://example.com ，抓取网页内容后整理成报告",
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "抓网页"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["policy"] == "hermes_fallback"
    assert response["_planner"]["reason"] == "external_system_task"
    assert client.cloud_calls == 1
    assert planner.calls == []


def test_file_task_model_client_auto_policy_stays_native_for_supported_pptx_design_tool():
    planner = FakePlannerAdapter(
        responses=[{"content": "pptx design planner response", "tool_calls": []}],
    )
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="目前这个 pptx 没有风格设计，请帮我设计主题和排版",
        files=[FileTaskFile(path="deck.pptx", name="deck.pptx", type="pptx")],
        target_path="deck.pptx",
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "设计 PPT"}],
        system="system prompt",
        tools=[{"name": "design_pptx_theme_layout"}, {"name": "write_pptx_slides"}, {"name": "add_pptx_slides"}],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["backend"] == "native"
    assert response["_planner"]["policy"] == "native_only"
    assert response["_planner"]["reason"] == "covered_by_koto_native"
    assert client.cloud_calls == 1
    assert planner.calls == []


def test_file_task_model_client_auto_policy_falls_back_to_native_without_external_backend():
    planner = FakePlannerAdapter(available=False, reason="planner bridge missing")
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="访问 https://example.com ，抓取网页内容后整理成报告",
        options={"planner_policy": "auto"},
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "抓网页"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert response["_planner"]["policy"] == "native_only"
    assert "no_external_backend_available" in response["_planner"]["reason"]
    assert client.cloud_calls == 1


def test_capability_matrix_matches_excel_to_docx_write_flow():
    request = FileTaskRequest(
        task="把这个 Excel 表格加入到当前 Word 文档里",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        files=[FileTaskFile(path="finance.xlsx", name="finance.xlsx", type="xlsx")],
        target_path="report.docx",
    )

    assert "insert_excel_as_docx_table" in file_task_capability.matched_native_capability_names(request)


def test_capability_matrix_matches_chart_task_to_sandbox_python():
    request = FileTaskRequest(
        task="根据当前表格生成一个柱状图并输出结果",
        current_file=FileTaskFile(path="metrics.xlsx", name="metrics.xlsx", type="xlsx"),
    )

    assert "run_python_code" in file_task_capability.matched_native_capability_names(request)


def test_capability_matrix_matches_chart_into_docx_write_flow():
    request = FileTaskRequest(
        task="把当前表格画成图并加入到 report.docx",
        current_file=FileTaskFile(path="finance.xlsx", name="finance.xlsx", type="xlsx"),
        files=[FileTaskFile(path="report.docx", name="report.docx", type="docx", target=True)],
        target_path="report.docx",
    )

    matched = file_task_capability.matched_native_capability_names(request)

    assert "run_python_code" in matched
    assert "insert_image_into_docx" in matched


def test_capability_matrix_does_not_match_annotation_without_file_context():
    request = FileTaskRequest(task="帮我加批注")

    assert file_task_capability.matched_native_capability_names(request) == []


def test_native_tool_gap_for_request_uses_capability_matrix_for_excel_to_docx_flow(monkeypatch):
    request = FileTaskRequest(
        task="把这个 Excel 表格加入到当前 Word 文档里",
        current_file=FileTaskFile(path="report.docx", name="report.docx", type="docx"),
        files=[FileTaskFile(path="finance.xlsx", name="finance.xlsx", type="xlsx")],
        target_path="report.docx",
    )

    monkeypatch.setattr(
        file_task_capability,
        "_has_native_tool",
        lambda tool_name: False if tool_name == "insert_excel_as_docx_table" else True,
    )

    gap = file_task_capability.native_tool_gap_for_request(request)

    assert gap is not None
    assert gap["missing_capability"] == "insert_excel_as_docx_table"
    assert gap["proposed_tool"]["name"] == "insert_excel_as_docx_table"


def test_build_file_capability_profile_marks_pdf_ocr_and_annotation_as_best_effort():
    profile = file_task_capability.build_file_capability_profile(file_type="pdf", path="scan.pdf")

    assert profile["format"] == "pdf"
    assert profile["workspace"]["edit_mode"] == "annotate_only"
    assert profile["task"]["analysis_mode"] == "native_with_ocr"
    assert profile["task"]["annotation_support"] == "best_effort"
    assert profile["ocr_mode"] == "fallback"


def test_build_request_capability_profiles_includes_target_path_contract():
    request = FileTaskRequest(
        task="把汇总写到新的文档里",
        current_file=FileTaskFile(path="metrics.xlsx", name="metrics.xlsx", type="xlsx"),
        target_path="summary.docx",
    )

    profiles = file_task_capability.build_request_capability_profiles(request)

    assert len(profiles) == 2
    target = next(profile for profile in profiles if profile["target"])
    assert "target_path" in target["roles"]
    assert target["format"] == "docx"
    assert target["task"]["write_support"] == "native"


def test_hermes_planner_adapter_supports_local_embedded_bridge(tmp_path):
    (tmp_path / "run_agent.py").write_text("class AIAgent:\n    pass\n", encoding="utf-8")
    adapter = HermesPlannerAdapter(repo_path=str(tmp_path))

    support = adapter.support(FileTaskRequest(task="总结文档"))

    assert support.available is True
    assert support.detected is True
    assert support.repo_path == str(tmp_path)


def test_hermes_planner_adapter_infers_non_empty_default_model(monkeypatch, tmp_path):
    (tmp_path / "run_agent.py").write_text("class AIAgent:\n    pass\n", encoding="utf-8")
    adapter = HermesPlannerAdapter(repo_path=str(tmp_path))
    monkeypatch.delenv("KOTO_HERMES_PLANNER_MODEL", raising=False)
    monkeypatch.setitem(sys.modules, "web.app", SimpleNamespace(MODEL_MAP={"FILE_TASK": "fake/default-model"}))

    inferred = adapter._infer_model(FileTaskRequest(task="总结文档"))

    assert inferred == "fake/default-model"


def test_hermes_planner_adapter_uses_embedded_agent_and_normalizes_response(monkeypatch, tmp_path):
    (tmp_path / "run_agent.py").write_text("class AIAgent:\n    pass\n", encoding="utf-8")
    captured = {}

    class FakeHermesAgent:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def run_conversation(self, **kwargs):
            captured["run"] = kwargs
            return {
                "final_response": json.dumps(
                    {
                        "content": "先读取文件再继续。",
                        "tool_calls": [
                            {
                                "name": "parse_file_to_text",
                                "args": {"path": "report.docx", "max_chars": 4000},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                "api_calls": 1,
                "completed": True,
                "turn_exit_reason": "completed",
                "model": "fake/hermes",
            }

    adapter = HermesPlannerAdapter(repo_path=str(tmp_path))
    monkeypatch.setattr(adapter, "_load_agent_class", lambda: FakeHermesAgent)
    request = FileTaskRequest(
        task="总结当前文档",
        run_id="hermes_bridge_demo",
        options={"planner_backend": "hermes", "planner_model": "fake/hermes"},
    )

    response = adapter.call(
        request=request,
        messages=[{"role": "user", "content": "先读文档内容，再决定是否改写。"}],
        system="只允许使用 Koto 工具。",
        tools=[{"name": "parse_file_to_text", "parameters": {"type": "object"}}],
    )

    assert response["content"] == "先读取文件再继续。"
    assert response["tool_calls"] == [
        {"name": "parse_file_to_text", "args": {"path": "report.docx", "max_chars": 4000}}
    ]
    assert response["_planner"]["backend"] == "hermes"
    assert response["_planner"]["transport"] == "embedded"
    assert captured["init"]["enabled_toolsets"] == []
    assert captured["init"]["disabled_toolsets"] == []
    assert captured["init"]["quiet_mode"] is True
    assert captured["run"]["task_id"] == "hermes_bridge_demo"
    assert "parse_file_to_text" in captured["run"]["user_message"]
    assert "只允许使用 Koto 工具。" in captured["run"]["system_message"]


def test_hermes_planner_adapter_normalizes_tool_gap_response(monkeypatch, tmp_path):
    (tmp_path / "run_agent.py").write_text("class AIAgent:\n    pass\n", encoding="utf-8")

    class FakeHermesAgent:
        def __init__(self, **kwargs):
            pass

        def run_conversation(self, **kwargs):
            return {
                "final_response": json.dumps(
                    {
                        "content": "当前任务需要新的 Koto 工具。",
                        "tool_calls": [],
                        "tool_gap": {
                            "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
                            "missing_capability": "read_cad_file",
                            "why_missing": "allowlist 中没有可读取 dwg 的工具。",
                            "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
                            "proposed_tool": {
                                "name": "read_cad_file",
                                "description": "解析 DWG/DXF 为可检索的结构化文本。",
                                "parameters": {"type": "object"},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                "api_calls": 1,
                "completed": True,
                "turn_exit_reason": "completed",
            }

    adapter = HermesPlannerAdapter(repo_path=str(tmp_path))
    monkeypatch.setattr(adapter, "_load_agent_class", lambda: FakeHermesAgent)

    response = adapter.call(
        request=FileTaskRequest(task="分析 CAD 文件", options={"planner_backend": "hermes"}),
        messages=[{"role": "user", "content": "分析 CAD 文件"}],
        system="只允许使用 Koto 工具。",
        tools=[],
    )

    assert response["content"] == "当前任务需要新的 Koto 工具。"
    assert response["tool_calls"] == []
    assert response["tool_gap"] == {
        "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
        "missing_capability": "read_cad_file",
        "why_missing": "allowlist 中没有可读取 dwg 的工具。",
        "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
        "proposed_tool": {
            "name": "read_cad_file",
            "description": "解析 DWG/DXF 为可检索的结构化文本。",
            "parameters": {"type": "object"},
            "returns": "",
            "rationale": "",
        },
    }


def test_hermes_planner_prompts_reference_shared_tool_design_protocol(tmp_path):
    (tmp_path / "run_agent.py").write_text("class AIAgent:\n    pass\n", encoding="utf-8")
    adapter = HermesPlannerAdapter(repo_path=str(tmp_path))

    system_message = adapter._build_system_message("只允许使用 Koto 工具。")
    user_message = adapter._build_user_message(
        request=FileTaskRequest(task="分析 CAD 文件", options={"planner_backend": "hermes"}),
        messages=[{"role": "user", "content": "分析 CAD 文件"}],
        tools=[{"name": "parse_file_to_text", "parameters": {"type": "object"}}],
    )

    assert TOOL_DESIGN_PROTOCOL in system_message
    assert "优先组合多个现有工具" in system_message
    assert f'"tool_design_protocol": "{TOOL_DESIGN_PROTOCOL}"' in user_message
    assert '"required_response_shape"' in user_message


def test_file_task_runtime_executes_external_planner_tool_calls():
    planner = FakePlannerAdapter(
        responses=[
            {
                "content": "准备写入 Word。",
                "tool_calls": [
                    {
                        "name": "write_docx_content",
                        "args": {"path": "report.docx", "paragraphs": '[{"text":"hello"}]'},
                    }
                ],
            },
            {"content": "已完成。", "tool_calls": []},
        ]
    )
    model_client = FileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))

    def fake_executor(tool_name, args):
        if tool_name == "write_docx_content":
            return json.dumps(
                {
                    "path": args["path"],
                    "operation": tool_name,
                    "summary": "已写入 1 个段落到 Word 文档",
                    "file_type": "docx",
                    "change_type": "modify",
                    "focus": True,
                },
                ensure_ascii=False,
            )
        if tool_name == "verify_task_completion":
            return json.dumps(
                {"completed": True, "confidence": 0.95, "summary": "写入已核验"},
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected tool call: {tool_name}")

    request = FileTaskRequest(
        task="修改当前文件并保存",
        run_id="external_planner_demo",
        options={"planner_backend": "hermes"},
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=model_client).run(request))
    file_changed = next(event for event in events if event.type == "file.changed")
    check_finished = next(event for event in events if event.type == "check.finished")

    assert file_changed.payload["path"] == "report.docx"
    assert check_finished.payload["status"] == "verified"
    assert events[-1].payload["completed_task"] is True


def test_file_task_runtime_surfaces_external_planner_textual_tool_gap_as_next_action_artifact():
    planner = FakePlannerAdapter(
        responses=[
            {
                "content": json.dumps(
                    {
                        "content": "当前任务需要新的 Koto 工具。",
                        "tool_calls": [],
                        "tool_gap": {
                            "summary": "当前缺少读取 CAD 文件的 Koto 原生工具。",
                            "missing_capability": "read_cad_file",
                            "why_missing": "allowlist 中没有可读取 dwg 的工具。",
                            "suggested_next_step": "先实现只读 CAD 解析工具，再决定写入方案。",
                            "proposed_tool": {
                                "name": "read_cad_file",
                                "description": "解析 DWG/DXF 为可检索的结构化文本。",
                                "parameters": {"type": "object"},
                                "acceptance_tests": ["DWG 示例文件可以返回图层和实体摘要。"],
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                "tool_calls": [],
            }
        ]
    )
    model_client = FileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(
        task="分析 CAD 文件",
        run_id="external_planner_tool_gap_demo",
        target_path="drawing.dwg",
        options={"planner_backend": "hermes"},
    )

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=model_client).run(request))

    planner_selected = next(event for event in events if event.type == "planner.selected")
    tool_missing = next(event for event in events if event.type == "tool.missing")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")
    artifact = tool_missing.payload["next_action_artifact"]

    assert planner_selected.payload["backend"] == "hermes"
    assert planner_selected.payload["source"] == "external"
    assert planner_selected.payload["policy"] == "explicit_backend"
    assert tool_missing.payload["missing_capability"] == "read_cad_file"
    assert tool_missing.payload["summary"] == "当前缺少读取 CAD 文件的 Koto 原生工具。"
    assert artifact["tool_design_protocol"] == TOOL_DESIGN_PROTOCOL
    assert artifact["title"] == "Koto 下一步：read_cad_file"
    assert artifact["target_path"] == "drawing.dwg"
    assert "DWG 示例文件可以返回图层和实体摘要。" in artifact["acceptance_criteria"]
    assert check_finished.payload["status"] == "tool_gap"
    assert check_finished.payload["next_action_artifact"] == artifact
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["next_action_artifact"] == artifact


def test_file_task_model_client_raises_when_explicit_planner_is_required():
    planner = FakePlannerAdapter(available=False, reason="planner bridge missing")
    client = TrackingFileTaskModelClient(planner_registry=FileTaskPlannerRegistry([planner]))
    request = FileTaskRequest(task="总结文档", options={"planner_backend": "hermes"})

    with pytest.raises(RuntimeError, match="planner bridge missing"):
        client.call(
            request=request,
            messages=[{"role": "user", "content": "总结"}],
            system="system prompt",
            tools=[],
        )