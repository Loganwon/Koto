import json

from app.core.agent import file_task_capability
from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
from app.core.agent.file_task_model import FileTaskModelClient
from app.core.agent.file_task_planner import (
    FileTaskPlannerRegistry,
    FileTaskPlannerSupport,
    default_file_task_planner_adapters,
)
from app.core.agent.file_task_runtime import FileTaskRuntime


class FakePlannerAdapter:
    def __init__(self, backend_name="test_planner", *, available=True, responses=None, reason="planner unavailable"):
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


def test_external_planner_registry_is_empty_by_default():
    assert default_file_task_planner_adapters() == []
    assert FileTaskPlannerRegistry().describe(FileTaskRequest(task="总结文档")) == []


def test_external_planner_registry_stays_empty_with_retired_enable_flag():
    assert default_file_task_planner_adapters() == []
    assert FileTaskPlannerRegistry().describe(FileTaskRequest(task="总结文档")) == []


def test_file_task_request_from_mapping_ignores_legacy_external_planner_fields():
    request = FileTaskRequest.from_mapping(
        {
            "task": "总结文档",
            "planner_backend": "retired_external",
            "planner_policy": "prefer_external",
            "planner_command": ["python", "planner_bridge.py"],
            "planner_timeout": 42,
            "planner_allow_native_fallback": True,
            "planner_options": {"transport": "stdin_json"},
        }
    )

    assert request.options == {}


def test_file_task_model_client_uses_native_model_path_even_with_legacy_planner_options():
    client = TrackingFileTaskModelClient()
    request = FileTaskRequest(
        task="总结文档",
        options={
            "planner_backend": "retired_external",
            "planner_policy": "prefer_external",
            "planner_allow_native_fallback": True,
        },
    )

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[{"name": "parse_file_to_text"}],
    )

    assert response["content"] == "cloud fallback"
    assert "_planner" not in response
    assert client.cloud_calls == 1


def test_file_task_capability_no_longer_exports_planner_policy_api():
    assert not hasattr(file_task_capability, "supported_planner_policies")


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
    assert client.cloud_calls == 1
    assert client.local_calls == [
        {
            "request": request,
            "messages": [{"role": "user", "content": "总结"}],
            "system": "system prompt",
            "tools": [{"name": "parse_file_to_text"}],
        }
    ]


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


def test_file_task_runtime_strips_external_planner_options_before_model_call():
    class RecordingModelClient:
        def __init__(self):
            self.requests = []

        def call(self, *, request, messages, system, tools):
            self.requests.append(request)
            return {
                "content": "准备写入 Word。",
                "tool_calls": [
                    {
                        "name": "write_docx_content",
                        "args": {"path": "report.docx", "paragraphs": '[{"text":"hello"}]'},
                    }
                ],
            }

    model_client = RecordingModelClient()

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
        run_id="native_planner_sanitize_demo",
        options={
            "planner_backend": "retired_external",
            "planner_policy": "prefer_external",
            "planner_command": ["python", "planner.py"],
        },
    )

    events = list(FileTaskRuntime(tool_executor=fake_executor, model_client=model_client).run(request))
    run_started = next(event for event in events if event.type == "run.started")
    file_changed = next(event for event in events if event.type == "file.changed")
    check_finished = next(event for event in events if event.type == "check.finished")

    assert run_started.payload["planner_backend"] == "native"
    assert run_started.payload["planner_policy"] == "native_only"
    assert model_client.requests
    assert model_client.requests[0].options["planner_policy"] == "native_only"
    assert model_client.requests[0].options["planner_runtime_reason"] == "file_task_native_only"
    assert "planner_backend" not in model_client.requests[0].options
    assert "planner_command" not in model_client.requests[0].options
    assert file_changed.payload["path"] == "report.docx"
    assert check_finished.payload["status"] == "verified"
    assert events[-1].payload["completed_task"] is True


def test_file_task_runtime_keeps_unknown_file_analysis_on_native_path_without_external_planner():
    request = FileTaskRequest(
        task="分析 CAD 文件",
        run_id="native_unknown_file_demo",
        target_path="drawing.dwg",
        options={"planner_backend": "retired_external"},
    )

    def forbidden_model(**kwargs):
        raise AssertionError("native tool gap should be resolved before model call")

    events = list(FileTaskRuntime(tool_executor=lambda name, args: "", model_client=forbidden_model).run(request))
    run_started = next(event for event in events if event.type == "run.started")
    check_finished = next(event for event in events if event.type == "check.finished")
    run_finished = next(event for event in events if event.type == "run.finished")

    assert run_started.payload["planner_backend"] == "native"
    assert run_started.payload["planner_policy"] == "native_only"
    assert run_started.payload["target_file_type"] == "dwg"
    assert check_finished.payload["status"] == "model_unavailable"
    assert check_finished.payload["runtime"]["execution_path"] == "native"
    assert run_finished.payload["completed_task"] is False
    assert run_finished.payload["planner_backend"] == "native"


def test_file_task_model_client_does_not_accept_legacy_planner_registry_argument():
    request = FileTaskRequest(task="总结文档", options={"planner_backend": "retired_external"})
    client = TrackingFileTaskModelClient()

    response = client.call(
        request=request,
        messages=[{"role": "user", "content": "总结"}],
        system="system prompt",
        tools=[],
    )

    assert response["content"] == "cloud fallback"
    assert client.cloud_calls == 1
