#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for the File Assistant AI stream endpoint.
Validates:
1. SSE streaming response format
2. All action types (polish, translate, find_replace, find_reference, etc.)
3. Full-text context injection
4. Chart rerun endpoint
"""

import json
import io
import os
import re
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Ensure project root is importable ──
ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from unit.workspace_css_contract import read_workspace_stylesheet_contract


# ── Helper ──

def parse_sse_events(response_data: bytes) -> list:
    """Parse SSE response bytes into list of event dicts."""
    events = []
    for chunk in response_data.decode("utf-8", errors="replace").split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            try:
                events.append(json.loads(chunk[6:]))
            except json.JSONDecodeError:
                pass
    return events


def _minimal_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
            "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
            "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
            "<w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


def _write_minimal_docx(path: Path) -> None:
    path.write_bytes(_minimal_docx_bytes())


# ── Mock LLM fixture ──

class FakeChunk:
    def __init__(self, text):
        self.text = text


def _make_fake_stream(prompt_keyword_responses: dict):
    """Create a fake generate_content_stream that returns deterministic output."""
    def fake_stream(model, contents, config=None):
        for keyword, response in prompt_keyword_responses.items():
            if keyword in str(contents):
                yield FakeChunk(response)
                return
        yield FakeChunk("默认 AI 回复。")
    return fake_stream


@pytest.fixture
def app_client():
    """Create a Flask test client with mocked LLM."""
    # Mock the Gemini client before importing app
    mock_client = MagicMock()
    mock_client.models.generate_content_stream = _make_fake_stream({
        "润色": "这是一段经过精心润色的优雅文本。",
        "翻译": "This is the translated text.",
        "总结": "本文主要讨论了三个核心观点。",
        "替换": '{"replacements": [{"from": "你好", "to": "您好"}, {"from": "世界", "to": "地球"}], "summary": "共替换 2 处"}',
        "引用": "1. 【论文】Smith et al. (2024) — AI辅助写作综述\n   链接：待核实",
        "检查": "1. 【第2行】你好 → 您好（更正式）",
        "改写": "这是用全新措辞表达的内容。",
        "续写": "接下来，我们将探讨更深层次的问题。",
    })

    with patch.dict("sys.modules", {}):
        # We need to patch the client object in web.app
        try:
            import app.core.agent.agent_loop as agent_loop_module
            from app.core.security.output_validator import OutputValidator
            from app.core.agent.lifecycle import evt_error, evt_stream_chunk, evt_task_complete
            from web.app import app
            app.config["TESTING"] = True
            # Patch the client and types (to avoid google.genai circular import under test)
            import web.app as web_app_module
            original_client = getattr(web_app_module, "client", None)
            original_api_key = getattr(web_app_module, "API_KEY", None)
            original_types = getattr(web_app_module, "types", None)
            original_llm_judge = getattr(OutputValidator, "_llm_judge")
            original_loop_run = agent_loop_module.KotoAgentLoop.run
            mock_types = MagicMock()
            mock_types.GenerateContentConfig.return_value = MagicMock()

            default_action_results = {
                "polish": "这是一段经过精心润色的优雅文本。",
                "translate": "This is the translated text.",
                "summary": "本文主要讨论了三个核心观点。",
                "find_replace": '{"replacements": [{"from": "你好", "to": "您好"}, {"from": "世界", "to": "地球"}], "summary": "共替换 2 处"}',
                "find_reference": "1. 【论文】Smith et al. (2024) — AI辅助写作综述\n   链接：待核实",
                "check": "1. 【第2行】你好 → 您好（更正式）",
                "rewrite": "这是用全新措辞表达的内容。",
                "continue": "接下来，我们将探讨更深层次的问题。",
                "custom_instruction": "已按要求处理当前内容。",
            }

            def fake_loop_run(self, request):
                model_mode = (getattr(request, "model_mode", "") or "").strip().lower()
                action_name = (getattr(request, "action_type", "") or "").strip().lower()

                if model_mode == "local":
                    if not agent_loop_module._is_ollama_alive():
                        yield evt_error("Ollama not running")
                        return
                    result_text = "本地Ollama响应"
                elif model_mode == "cloud":
                    result_text = "云端Gemini响应"
                else:
                    result_text = default_action_results.get(action_name, "默认 AI 回复。")

                yield evt_stream_chunk(result_text)
                yield evt_task_complete(result=result_text)

            web_app_module.client = mock_client
            web_app_module.API_KEY = "test-key-mock"
            web_app_module.types = mock_types
            OutputValidator._llm_judge = classmethod(lambda cls, text, original_prompt: None)
            agent_loop_module.KotoAgentLoop.run = fake_loop_run
            yield app.test_client()
            # Restore
            web_app_module.client = original_client
            web_app_module.API_KEY = original_api_key
            web_app_module.types = original_types
            OutputValidator._llm_judge = original_llm_judge
            agent_loop_module.KotoAgentLoop.run = original_loop_run
        except ImportError as e:
            pytest.skip(f"Cannot import web.app: {e}")


# ══════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════

class TestEditorAIStream:
    """Tests for the current file-task editor AI stream."""

    def _assert_editor_ai_stream_removed(self, app_client, payload):
        resp = app_client.post("/api/editor/ai/stream", json=payload)
        assert resp.status_code == 404

    def test_file_task_stream_executes_xlsx_to_docx_write_loop(self, app_client, tmp_path, monkeypatch):
        import openpyxl
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime

        workbook_path = tmp_path / "sales.xlsx"
        target_path = tmp_path / "target.docx"

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "汇总表"
        sheet.append(["客户名称", "产品名称", "数量"])
        sheet.append(["杭州新汇鑫光电有限公司", "LASER", 1])
        sheet.append(["山东镭鸟激光设备有限公司", "LASER", 2])
        workbook.save(workbook_path)

        document = Document()
        document.add_paragraph("雷鸟访谈问题")
        document.save(target_path)

        responses = iter([
            {
                "content": "先读取 Excel。",
                "tool_calls": [
                    {
                        "name": "read_sheet_data",
                        "args": {"path": str(workbook_path), "sheet_name": "Sheet1", "max_rows": "2"},
                    }
                ],
            },
            {
                "content": "把 Excel 表格加入 Word。",
                "tool_calls": [
                    {
                        "name": "insert_excel_as_docx_table",
                        "args": {
                            "source_path": str(workbook_path),
                            "target_path": str(target_path),
                            "sheet_name": "Sheet1",
                            "table_title": "销售台账数据",
                            "max_rows": "2",
                        },
                    }
                ],
            },
            {"content": "已将销售台账数据加入 Word。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            return next(responses)

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "把 xlsx 表格加入 docx",
                "session_id": "editor_demo",
                "model_mode": "local",
                "target_path": str(target_path),
                "files": [
                    {"path": str(workbook_path), "name": "销售台账.xlsx", "type": "xlsx", "content": "Excel 上下文"},
                    {"path": str(target_path), "name": "雷鸟访谈问题.docx", "type": "docx", "content": "Word 上下文", "target": True},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        read_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "read_sheet_data"
        )
        file_changed = next(event for event in events if event.get("type") == "file.changed")
        check_finished = [
            event for event in events
            if event.get("type") == "check.finished"
        ][-1]
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert "汇总表" in str(read_finished.get("payload", {}).get("result_preview", ""))
        assert file_changed["payload"]["sheet"] == "汇总表"
        assert file_changed["payload"]["requested_sheet"] == "Sheet1"
        assert file_changed["payload"]["rows_written"] == 2
        assert file_changed["payload"]["columns_written"] == 3
        assert "used '汇总表' instead" in file_changed["payload"]["warning"]
        assert check_finished["payload"]["status"] == "verified"
        assert run_finished["payload"]["completed_task"] is True

        saved = Document(str(target_path))
        assert len(saved.tables) == 1
        assert saved.tables[0].cell(1, 0).text == "杭州新汇鑫光电有限公司"
        assert saved.tables[0].cell(2, 0).text == "山东镭鸟激光设备有限公司"

    def test_file_task_stream_does_not_split_xlsx_source_and_docx_target_without_explicit_pin(self, app_client, tmp_path, monkeypatch):
        import openpyxl
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime

        workbook_path = tmp_path / "financial-model.xlsx"
        target_path = tmp_path / "interview-questions.docx"

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "P&L"
        sheet.append(["年份", "收入"])
        sheet.append(["2025E", 100])
        workbook.save(workbook_path)

        document = Document()
        document.add_paragraph("雷鸟访谈问题")
        document.save(target_path)

        responses = iter([
            {
                "content": "先读取 Excel。",
                "tool_calls": [
                    {
                        "name": "read_sheet_data",
                        "args": {"path": str(workbook_path), "sheet_name": "P&L", "max_rows": "2"},
                    }
                ],
            },
            {
                "content": "把 Excel 表格加入 Word。",
                "tool_calls": [
                    {
                        "name": "insert_excel_as_docx_table",
                        "args": {
                            "source_path": str(workbook_path),
                            "target_path": str(target_path),
                            "sheet_name": "P&L",
                            "table_title": "财务预测摘要表",
                            "max_rows": "2",
                        },
                    }
                ],
            },
            {"content": "已将财务预测加入 Word。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            return next(responses)

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "整理 xlsx 中的财务预测，并加入 docx",
                "session_id": "editor_demo",
                "model_mode": "local",
                "files": [
                    {"path": str(workbook_path), "name": "雷鸟创新-financial model.xlsx", "type": "xlsx", "content": "Excel 上下文"},
                    {"path": str(target_path), "name": "雷鸟访谈问题.docx", "type": "docx", "content": "Word 上下文"},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        file_changed = next(event for event in events if event.get("type") == "file.changed")
        check_finished = [event for event in events if event.get("type") == "check.finished"][-1]

        assert resp.status_code == 200
        assert not any(event.get("type") == "multi_target.started" for event in events)
        assert run_started.get("payload", {}).get("target_path") == str(target_path)
        assert run_started.get("payload", {}).get("write_intent") is True
        assert file_changed.get("payload", {}).get("path") == str(target_path)
        assert check_finished.get("payload", {}).get("status") != "no_file_change"
        assert len(Document(str(target_path)).tables) == 1

    def test_file_task_stream_finance_chart_and_findings_write_back_to_docx(self, app_client, tmp_path, monkeypatch):
        import openpyxl
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime

        workbook_path = tmp_path / "financial-model.xlsx"
        target_path = tmp_path / "interview-questions.docx"
        chart_path = tmp_path / "financial_chart.png"

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "P&L"
        sheet.append(["项目", "2025E", "2026E"])
        sheet.append(["收入合计", 34807.4, 59605.0])
        sheet.append(["净利润", -9196.4, -1138.6])
        workbook.save(workbook_path)

        document = Document()
        document.add_paragraph("雷鸟访谈问题")
        document.save(target_path)

        responses = iter([
            {
                "content": "先检查工作簿结构。",
                "tool_calls": [
                    {
                        "name": "inspect_workbook_structure",
                        "args": {"path": str(workbook_path), "sample_rows_per_sheet": "5", "max_formula_examples_per_sheet": "3"},
                    }
                ],
            },
            {
                "content": "读取关键工作表。",
                "tool_calls": [
                    {
                        "name": "read_sheet_data",
                        "args": {"path": str(workbook_path), "sheet_name": "P&L", "max_rows": "5"},
                    }
                ],
            },
            {
                "content": "生成图表图片。",
                "tool_calls": [
                    {
                        "name": "run_python_code",
                        "args": {
                            "code": (
                                "from pathlib import Path\n"
                                "import base64\n"
                                f"output_path = r{str(chart_path)!r}\n"
                                "Path(output_path).write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+tm0YAAAAASUVORK5CYII='))\n"
                                "print('KOTO_CREATED:' + output_path)\n"
                            ),
                            "timeout": 30,
                        },
                    }
                ],
            },
            {
                "content": "把图插入目标文档。",
                "tool_calls": [
                    {
                        "name": "insert_image_into_docx",
                        "args": {
                            "path": str(target_path),
                            "image_path": str(chart_path),
                            "title": "财务预测趋势图",
                            "caption": "收入与利润走势示意",
                            "width_inches": "5.2",
                        },
                    }
                ],
            },
            {
                "content": "把主要问题写入目标文档。",
                "tool_calls": [
                    {
                        "name": "write_docx_content",
                        "args": {
                            "path": str(target_path),
                            "paragraphs": json.dumps([
                                {"text": "主要问题"},
                                {"text": "1. 预测期净利润前两年仍为负，盈利拐点依赖后续年份假设。"},
                                {"text": "2. 需要进一步核查收入增长与利润改善是否匹配。"}
                            ], ensure_ascii=False),
                        },
                    }
                ],
            },
            {"content": "已完成图表和问题写回。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            return next(responses)

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "分析这个财务模型预测，做成一张图，并且将图和可能存在的问题加入docx",
                "session_id": "editor_demo",
                "model_mode": "local",
                "files": [
                    {"path": str(workbook_path), "name": workbook_path.name, "type": "xlsx", "content": "Excel 上下文"},
                    {"path": str(target_path), "name": target_path.name, "type": "docx", "content": "Word 上下文"},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        inspect_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "inspect_workbook_structure"
        )
        python_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "run_python_code"
        )
        image_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "insert_image_into_docx"
        )
        narrative_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "write_docx_content"
        )
        docx_changes = [
            event for event in events
            if event.get("type") == "file.changed" and event.get("payload", {}).get("path") == str(target_path)
        ]
        check_finished = next(event for event in events if event.get("type") == "check.finished")
        run_finished = next(event for event in events if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert not any(event.get("type") == "multi_target.started" for event in events)
        assert inspect_finished.get("payload", {}).get("success") is True
        assert python_finished.get("payload", {}).get("success") is True
        assert image_finished.get("payload", {}).get("success") is True
        assert narrative_finished.get("payload", {}).get("success") is True
        assert any(change.get("payload", {}).get("operation") == "insert_image_into_docx" for change in docx_changes)
        assert any(change.get("payload", {}).get("operation") == "write_docx_content" for change in docx_changes)
        assert check_finished.get("payload", {}).get("status") == "verified"
        assert run_finished.get("payload", {}).get("completed_task") is True

        saved = Document(str(target_path))
        texts = [paragraph.text for paragraph in saved.paragraphs]
        assert "财务预测趋势图" in texts
        assert "收入与利润走势示意" in texts
        assert "主要问题" in texts
        assert len(saved.inline_shapes) == 1

    def test_file_task_stream_rejects_removed_one_shot_financial_report_tool(self, app_client, tmp_path, monkeypatch):
        import openpyxl
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime

        workbook_path = tmp_path / "financial-model.xlsx"
        target_path = tmp_path / "interview-questions.docx"

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "P&L"
        sheet.append(["项目", "2025E", "2026E", "2027E"])
        sheet.append(["收入合计", 1200, 1800, 2600])
        sheet.append(["毛利", 420, 720, 1170])
        sheet.append(["净利润", -120, 60, 280])
        workbook.save(workbook_path)

        document = Document()
        document.add_paragraph("雷鸟访谈问题")
        document.save(target_path)

        responses = iter([
            {
                "content": "尝试调用旧的一键财务图文报告工具。",
                "tool_calls": [
                    {
                        "name": "create_financial_forecast_docx_report",
                        "args": {
                            "source_path": str(workbook_path),
                            "target_path": str(target_path),
                            "sheet_name": "P&L",
                        },
                    }
                ],
            },
            {"content": "旧工具不可用，需改走统一多步任务流。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            return next(responses)

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "分析这个xslx财务预测，做成图，然后将分析和图都加入docx",
                "session_id": "editor_demo",
                "model_mode": "local",
                "files": [
                    {"path": str(workbook_path), "name": "雷鸟创新-financial model.xlsx", "type": "xlsx", "content": "Excel 上下文"},
                    {"path": str(target_path), "name": "雷鸟访谈问题.docx", "type": "docx", "content": "Word 上下文"},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        invalid_tool_finished = next(
            event for event in events
            if event.get("type") == "tool.finished"
            and event.get("payload", {}).get("tool_name") == "create_financial_forecast_docx_report"
        )
        docx_changes = [
            event for event in events
            if event.get("type") == "file.changed" and event.get("payload", {}).get("path") == str(target_path)
        ]
        check_finished = next(event for event in events if event.get("type") == "check.finished")
        run_finished = next(event for event in events if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert invalid_tool_finished.get("payload", {}).get("success") is False
        assert "allowlist" in invalid_tool_finished.get("payload", {}).get("result_preview", "")
        assert not docx_changes
        assert check_finished.get("payload", {}).get("status") in {"no_file_change", "needs_attention"}
        assert run_finished.get("payload", {}).get("completed_task") is False

        saved = Document(str(target_path))
        texts = [paragraph.text for paragraph in saved.paragraphs]
        assert texts == ["雷鸟访谈问题"]
        assert len(saved.inline_shapes) == 0

    def test_file_task_stream_reports_no_write_when_docx_is_unchanged(self, app_client, tmp_path, monkeypatch):
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime

        target_path = tmp_path / "target.docx"
        document = Document()
        document.add_paragraph("雷鸟访谈问题")
        document.save(target_path)

        responses = iter([
            {
                "content": "尝试把 Excel 表格加入 Word。",
                "tool_calls": [
                    {
                        "name": "insert_excel_as_docx_table",
                        "args": {
                            "source_path": str(tmp_path / "missing.xlsx"),
                            "target_path": str(target_path),
                            "sheet_name": "Sheet1",
                            "max_rows": "50",
                        },
                    }
                ],
            },
            {"content": "已完成。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            return next(responses)

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "把 xlsx 表格加入 docx",
                "session_id": "editor_demo",
                "target_path": str(target_path),
                "files": [
                    {"path": str(target_path), "name": "雷鸟访谈问题.docx", "type": "docx", "content": "Word 上下文", "target": True},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        insert_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "insert_excel_as_docx_table"
        )
        check_finished = next(event for event in events if event.get("type") == "check.finished")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert insert_finished["payload"]["success"] is False
        assert "File not found" in insert_finished["payload"]["result_preview"]
        assert not any(event.get("type") == "file.changed" for event in events)
        assert check_finished["payload"]["status"] == "no_file_change"
        assert run_finished["payload"]["completed_task"] is False
        assert len(Document(str(target_path)).tables) == 0

    def test_file_task_stream_infers_new_docx_target_for_pdf_summary_task(self, app_client, tmp_path, monkeypatch):
        import json
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime
        from app.core.agent import task_tools

        pdf_path = tmp_path / "中国博物馆数字技术应用及案例研究年度报告.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

        monkeypatch.setattr(
            task_tools,
            "parse_file_to_text",
            lambda path, max_chars=60000, start_page=None, end_page=None: "[Page 1]\n报告强调博物馆数字化转型与观众中心。",
        )

        responses = iter([
            {
                "content": "先读取 PDF 前几页内容。",
                "tool_calls": [
                    {
                        "name": "parse_file_to_text",
                        "args": {"path": str(pdf_path), "start_page": 1, "end_page": 15, "max_chars": 4000},
                    }
                ],
            },
            {
                "content": "把第一步总结写入新的 docx。",
                "tool_calls": [],
            },
            {"content": "已完成。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            payload = next(responses)
            if payload.get("content") == "把第一步总结写入新的 docx。":
                target_path = kwargs["request"].target_path
                return {
                    "content": payload["content"],
                    "tool_calls": [
                        {
                            "name": "write_docx_content",
                            "args": {
                                "path": target_path,
                                "paragraphs": json.dumps(
                                    [
                                        {"text": "《中国博物馆数字技术应用及案例研究年度报告》总结", "style": "Title"},
                                        {"text": "第一步：引言与报告结构概述", "style": "Heading 1"},
                                        {"text": "报告强调博物馆数字化转型从以物为中心转向以观众为中心。"},
                                    ],
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            return payload

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "这是一篇非常长的pdf，里面有大量内容。将整篇文章拆成分步任务逐步总结，并创建一个docx文件记录每一步要点，每步完成后更新docx。",
                "session_id": "editor_demo",
                "model_mode": "local",
                "files": [
                    {"path": str(pdf_path), "name": pdf_path.name, "type": "pdf", "content": "PDF 上下文"},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        write_tool = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "write_docx_content"
        )
        file_changed = next(event for event in events if event.get("type") == "file.changed")
        check_finished = next(event for event in events if event.get("type") == "check.finished")
        run_finished = next(event for event in events if event.get("type") == "run.finished")

        inferred_target = str(run_started.get("payload", {}).get("target_path") or "")
        saved_path = Path(inferred_target)
        if not saved_path.is_absolute():
            saved_path = Path(str(tmp_path)) / saved_path.name

        assert resp.status_code == 200
        assert inferred_target.endswith("_总结.docx")
        assert write_tool["payload"]["success"] is True
        assert file_changed["payload"]["path"] == inferred_target
        assert file_changed["payload"]["operation"] == "write_docx_content"
        assert check_finished["payload"]["status"] == "verified"
        assert run_finished["payload"]["completed_task"] is True

        saved = Document(str(saved_path))
        assert saved.paragraphs[0].text == "《中国博物馆数字技术应用及案例研究年度报告》总结"
        assert any("第一步：引言与报告结构概述" in paragraph.text for paragraph in saved.paragraphs)

    def test_file_task_stream_run_python_code_syncs_inferred_docx_target(self, app_client, tmp_path, monkeypatch):
        from docx import Document

        from app.core.agent.file_task_runtime import FileTaskRuntime
        from app.core.agent import task_tools

        pdf_path = tmp_path / "museum-report.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

        monkeypatch.setattr(
            task_tools,
            "parse_file_to_text",
            lambda path, max_chars=60000, start_page=None, end_page=None: "[Page 1]\n博物馆数字化转型需要围绕观众体验设计。",
        )

        responses = iter([
            {
                "content": "先读取 PDF 内容。",
                "tool_calls": [
                    {
                        "name": "parse_file_to_text",
                        "args": {"path": str(pdf_path), "start_page": 1, "end_page": 12, "max_chars": 4000},
                    }
                ],
            },
            {
                "content": "改用 Python 创建 docx 并写入第一步总结。",
                "tool_calls": [],
            },
            {"content": "已完成。", "tool_calls": []},
        ])

        def fake_call_model(self, **kwargs):
            payload = next(responses)
            if payload.get("content") == "改用 Python 创建 docx 并写入第一步总结。":
                target_path = kwargs["request"].target_path
                target_name = Path(target_path).name
                return {
                    "content": payload["content"],
                    "tool_calls": [
                        {
                            "name": "run_python_code",
                            "args": {
                                "code": (
                                    "from docx import Document\n"
                                    f"target_path = TASK_SANDBOX_FILE_PATHS[{target_name!r}]\n"
                                    "doc = Document()\n"
                                    "doc.add_paragraph('第一步：先提炼报告框架与问题意识。')\n"
                                    "doc.add_paragraph('博物馆数字化转型需要围绕观众体验设计。')\n"
                                    "doc.save(target_path)\n"
                                ),
                                "timeout": 30,
                            },
                        }
                    ],
                }
            return payload

        monkeypatch.setattr(FileTaskRuntime, "_call_model", fake_call_model)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "这是一篇非常长的pdf，里面有大量内容。将整篇文章拆成分步任务逐步总结，并创建一个docx文件记录每一步要点，每步完成后更新docx。",
                "session_id": "editor_demo",
                "model_mode": "local",
                "files": [
                    {"path": str(pdf_path), "name": pdf_path.name, "type": "pdf", "content": "PDF 上下文"},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        python_finished = next(
            event for event in events
            if event.get("type") == "tool.finished" and event.get("payload", {}).get("tool_name") == "run_python_code"
        )
        file_changed = next(event for event in events if event.get("type") == "file.changed")
        check_finished = next(event for event in events if event.get("type") == "check.finished")
        run_finished = next(event for event in events if event.get("type") == "run.finished")

        inferred_target = str(run_started.get("payload", {}).get("target_path") or "")
        saved_path = Path(inferred_target)

        assert resp.status_code == 200
        assert saved_path.is_file()
        assert python_finished["payload"]["success"] is True
        assert file_changed["payload"]["path"] == inferred_target
        assert file_changed["payload"]["operation"] == "run_python_code"
        assert check_finished["payload"]["status"] == "verified"
        assert run_finished["payload"]["completed_task"] is True

        saved = Document(str(saved_path))
        assert any("第一步：先提炼报告框架与问题意识。" in paragraph.text for paragraph in saved.paragraphs)
        assert any("博物馆数字化转型需要围绕观众体验设计。" in paragraph.text for paragraph in saved.paragraphs)

    def test_polish_returns_sse(self, app_client):
        """Legacy editor SSE route should be retired for polish requests."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "polish",
            "selection": "这段文字需要被润色一下。",
        })

    def test_polish_with_full_text_context(self, app_client):
        """Legacy editor SSE route should stay retired even when full_text is supplied."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "polish",
            "selection": "这段文字需要润色。",
            "full_text": "第一段落。这段文字需要润色。第三段落结尾。",
        })

    def test_translate_action(self, app_client):
        """Legacy editor SSE route should be retired for translate requests."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "translate",
            "selection": "你好世界",
        })

    def test_find_replace_action(self, app_client):
        """Legacy editor SSE route should be retired for find/replace requests."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "find_replace",
            "instruction": "把所有你好替换成您好",
            "full_text": "你好世界，你好中国，你好大家。",
        })

    def test_find_reference_action(self, app_client):
        """Legacy editor SSE route should be retired for reference lookup requests."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "find_reference",
            "selection": "人工智能在教育中的应用越来越广泛。",
            "full_text": "本文探讨人工智能在教育中的应用。",
        })

    def test_empty_selection_returns_error(self, app_client):
        """Legacy editor SSE route should be retired before legacy validation runs."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "polish",
            "selection": "",
            "instruction": "",
        })

    def test_custom_instruction_with_context(self, app_client):
        """Legacy editor SSE route should be retired for custom instructions too."""
        self._assert_editor_ai_stream_removed(app_client, {
            "action": "custom_instruction",
            "selection": "AI技术",
            "instruction": "用更学术的方式描述",
            "full_text": "本篇论文探讨AI技术的发展趋势。",
        })

    def test_ai_task_action_is_not_an_editor_stream_action(self, app_client):
        self._assert_editor_ai_stream_removed(
            app_client,
            {
                "action": "ai_task",
                "instruction": "整理当前文件",
                "session_id": "editor_demo",
                "file_name": "demo.docx",
                "file_type": "docx",
            },
        )

    def test_file_task_stream_emits_new_contract(self, app_client, monkeypatch):
        from app.core.agent.file_task_runtime import FileTaskRuntime

        monkeypatch.setattr(
            FileTaskRuntime,
            "_call_model",
            lambda self, **kwargs: {"content": "已总结：hello world", "tool_calls": []},
        )

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "总结这段选区",
                "selection": "hello world",
                "selection_source": "notes.txt",
                "session_id": "editor_demo",
            },
        )
        events = parse_sse_events(resp.get_data())
        event_types = [event.get("type") for event in events]
        run_started = next(event for event in events if event.get("type") == "run.started")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert "run.started" in event_types
        assert "task.classified" in event_types
        assert "plan.checked" in event_types
        assert "plan.created" in event_types
        assert "step.started" in event_types
        assert event_types.index("task.classified") < event_types.index("plan.checked")
        assert event_types.index("plan.checked") < event_types.index("plan.created")
        assert event_types.index("plan.created") < event_types.index("step.started")
        assert "check.started" in event_types
        assert "check.finished" in event_types
        assert "run.finished" in event_types
        assert [event.get("seq") for event in events] == list(range(1, len(events) + 1))
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert run_started.get("task_id")
        assert run_finished["payload"].get("completed_task") is True

    def test_file_task_stream_persists_task_identity_and_progress_history(self, app_client, monkeypatch):
        from app.core.agent.file_task_runtime import FileTaskRuntime
        from app.core.tasks.progress_bus import get_progress_bus
        from app.core.tasks.task_ledger import get_ledger

        session_id = "editor_persist_demo"
        monkeypatch.setattr(
            FileTaskRuntime,
            "_call_model",
            lambda self, **kwargs: {"content": "已总结：hello world", "tool_calls": []},
        )

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "总结这段选区",
                "selection": "hello world",
                "selection_source": "notes.txt",
                "session_id": session_id,
                "task_context": {
                    "context_version": "koto_task_context_v1",
                    "intent": {"request": "总结这段选区"},
                    "files": {"current": {"path": "notes.txt", "name": "notes.txt", "type": "txt"}},
                },
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        task_id = str(run_started.get("task_id") or "").strip()

        assert resp.status_code == 200
        assert task_id

        ledger = get_ledger()
        task = ledger.get(task_id, include_steps=True)
        assert task is not None
        assert task.session_id == session_id
        assert task.source == "file_task"
        assert task.status.value == "completed"

        metadata = json.loads(task.metadata)
        assert metadata["task_contract"] == "file_task_v1"
        assert "legacy_" + "task_contract" not in metadata
        assert metadata["run_id"] == run_started["run_id"]
        assert metadata["last_event_type"] == "run.finished"
        assert metadata["task_context"]["context_version"] == "koto_task_context_v1"
        assert metadata["task_context"]["files"]["current"]["path"] == "notes.txt"
        assert task.steps

        history = get_progress_bus().get_history(task_id)
        file_task_events = [item.to_dict() for item in history if item.event_type == "file_task_event"]
        assert file_task_events
        assert any(item["detail"]["event"]["type"] == "plan.checked" for item in file_task_events)
        assert file_task_events[-1]["detail"]["event"]["type"] == "run.finished"

    def test_file_task_stream_preserves_runtime_metadata_and_followup_context(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_runtime import FileTaskRuntime

        monkeypatch.setenv("KOTO_FILE_TASK_FOLLOWUP_PATH", str(tmp_path / "followups.json"))
        monkeypatch.setattr(
            FileTaskRuntime,
            "_call_model",
            lambda self, **kwargs: {
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
                "_planner": {
                    "backend": "legacy_external",
                    "source": "external",
                    "policy": "prefer_external",
                    "transport": "embedded",
                    "reason": "unsupported_file_types:dwg",
                },
            },
        )

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "修改 CAD 文件并导出总结",
                "session_id": "editor_demo",
                "target_path": "drawing.dwg",
            },
        )

        events = parse_sse_events(resp.get_data())
        tool_missing = next(event for event in events if event.get("type") == "tool.missing")
        check_finished = next(event for event in events if event.get("type") == "check.finished")
        run_finished = next(event for event in events if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert tool_missing["payload"]["runtime"]["execution_path"] == "native"
        assert tool_missing["payload"]["next_action_artifact"]["runtime_context"]["execution_path"] == "native"
        assert tool_missing["payload"]["next_action_artifact"]["source_task"] == "修改 CAD 文件并导出总结"
        assert tool_missing["payload"]["next_action_artifact"]["target_path"] == "drawing.dwg"
        assert tool_missing["payload"]["next_action_artifact"]["missing_capability"] == "read_cad_file"
        assert check_finished["payload"]["runtime"]["terminal_status"] == "tool_gap"
        assert run_finished["payload"]["runtime"]["execution_path"] == "native"
        assert run_finished["payload"]["runtime"]["terminal_status"] == "tool_gap"

    def test_file_task_stream_requires_task(self, app_client):
        resp = app_client.post("/api/editor/ai/task-stream", json={"selection": "hello"})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Missing 'task' parameter"

    def test_file_task_stream_routes_pdf_docx_translation_review_through_file_task_runtime(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskLedger
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        _write_minimal_docx(docx_path)

        captured = {}

        def fake_run(self, request):
            captured["request"] = request
            ledger = FileTaskLedger(request.run_id)
            yield ledger.event("plan.checked", {"passed": True, "routing": "unified_file_task"}, step_id="plan")
            yield ledger.event("run.started", {"task": request.task, "mode": "file_task_v1"}, step_id="run")
            yield ledger.event("plan.created", {"summary": "统一文件任务流已规划批注写回。", "steps": [{"id": "annotation_write", "title": "写入批注意见"}]}, step_id="plan")
            yield ledger.event("step_progress", {"detail": "已写入 2 条审校修订", "progress": 84, "file_updated": True, "path": str(docx_path), "file_path": str(docx_path), "supported": True}, step_id="annotation_write")
            yield ledger.event("tool.finished", {"tool_name": "annotate_file", "success": True, "result_preview": "已写入 2 条批注。"}, step_id="annotation_write")
            yield ledger.event("file.changed", {"path": str(docx_path), "file_path": str(docx_path), "file_type": "docx", "operation": "annotate_file", "summary": f"已将 2 条修订写回 {docx_path.name}。", "annotations_added": 2, "source_path": str(pdf_path)}, step_id="write")
            yield ledger.event("run.finished", {"summary": f"已更新 {docx_path.name}。", "completed_task": True, "mode": "file_task_v1"}, step_id="run")

        monkeypatch.setattr(bridge, "stream_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("task-stream must not call doc annotate bridge directly")))
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句，重新考虑中文翻译不当的部分或有复议可能性的用词或者替换成别的词的地方都标注出来。学术化翻译和中文学界常用词不对应的地方也标注出来，谨遵原著，不要有任何删减和添加。由于文件比较大内容比较多，我建议你将整个任务拆分成多个分段来处理，以保证最终结果的质量和任务可执行性",
                "session_id": "workspace_demo",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())

        assert resp.status_code == 200
        assert captured["request"].target_path == str(docx_path)
        assert events[0]["type"] == "plan.checked"
        assert events[0]["payload"]["routing"] == "unified_file_task"
        run_started = next(event for event in events if event["type"] == "run.started")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert any(event["type"] == "tool.finished" and event["payload"].get("tool_name") == "annotate_file" for event in events)
        assert any(event["type"] == "plan.created" for event in events)
        assert any(event["type"] == "step_progress" and event["payload"].get("file_updated") for event in events)
        assert any(event["type"] == "file.changed" and event["payload"].get("path") == str(docx_path) for event in events)
        assert run_finished["payload"]["completed_task"] is True

    def test_file_task_stream_routes_single_docx_annotation_through_file_task_runtime(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskLedger
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        docx_path = tmp_path / "interview.docx"
        _write_minimal_docx(docx_path)

        captured = {}

        def fake_run(self, request):
            captured["request"] = request
            ledger = FileTaskLedger(request.run_id)
            yield ledger.event("run.started", {"task": request.task, "mode": "file_task_v1"}, step_id="run")
            yield ledger.event("step_progress", {"detail": "已写入 1/2 条修订", "progress": 80, "file_updated": True, "path": str(docx_path), "file_path": str(docx_path), "supported": True}, step_id="annotation_write")
            yield ledger.event("tool.finished", {"tool_name": "annotate_file", "success": True, "result_preview": "已写入 2 条批注。"}, step_id="annotation_write")
            yield ledger.event("file.changed", {"path": str(docx_path), "file_path": str(docx_path), "file_type": "docx", "operation": "annotate_file", "summary": f"已将 2 条修订写回 {docx_path.name}。", "annotations_added": 2}, step_id="write")
            yield ledger.event("run.finished", {"summary": f"已更新 {docx_path.name}。", "completed_task": True, "mode": "file_task_v1"}, step_id="run")

        monkeypatch.setattr(bridge, "stream_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("task-stream must not call doc annotate bridge directly")))
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "将你觉得写得不好的地方批注出来",
                "session_id": "workspace_demo",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(docx_path), "name": "interview.docx", "type": "docx", "target": True},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert captured["request"].target_path == str(docx_path)
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert any(event["type"] == "tool.finished" and event["payload"].get("tool_name") == "annotate_file" for event in events)
        assert any(event["type"] == "step_progress" and event["payload"].get("file_updated") for event in events)
        assert any(event["type"] == "file.changed" and event["payload"].get("path") == str(docx_path) for event in events)
        assert run_finished["payload"]["completed_task"] is True

    def test_file_task_stream_routes_docx_style_review_prompt_through_file_task_runtime(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskLedger
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        docx_path = tmp_path / "humanise!.docx"
        _write_minimal_docx(docx_path)

        captured = {}

        def fake_run(self, request):
            captured["request"] = request
            ledger = FileTaskLedger(request.run_id)
            yield ledger.event("plan.checked", {"passed": True, "routing": "unified_file_task"}, step_id="plan")
            yield ledger.event("run.started", {"task": request.task, "mode": "file_task_v1"}, step_id="run")
            yield ledger.event("tool.finished", {"tool_name": "annotate_file", "success": True, "result_preview": "已写入批注意见。"}, step_id="annotation_write")
            yield ledger.event("file.changed", {"path": str(docx_path), "file_path": str(docx_path), "file_type": "docx", "operation": "annotate_file", "summary": f"已更新 {docx_path.name}。", "annotations_added": 2}, step_id="write")
            yield ledger.event("run.finished", {"summary": f"已更新 {docx_path.name}。", "completed_task": True, "mode": "file_task_v1"}, step_id="run")

        monkeypatch.setattr(bridge, "stream_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("task-stream must not call doc annotate bridge directly")))
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "把你觉得表达不通顺、像 AI 的地方标出来，并提出修改意见",
                "session_id": "workspace_demo",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(docx_path), "name": docx_path.name, "type": "docx", "target": True},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        plan_checked = next(event for event in events if event.get("type") == "plan.checked")
        run_started = next(event for event in events if event.get("type") == "run.started")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert captured["request"].task == "把你觉得表达不通顺、像 AI 的地方标出来，并提出修改意见"
        assert plan_checked["payload"]["routing"] == "unified_file_task"
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert any(event["type"] == "tool.finished" and event["payload"].get("tool_name") == "annotate_file" for event in events)
        assert run_finished["payload"]["completed_task"] is True

    def test_file_task_stream_routes_pdf_docx_translation_review_through_file_task_runtime_in_local_mode(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskLedger
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        _write_minimal_docx(docx_path)

        captured = {"request": None}

        def fake_run(self, request):
            captured["request"] = request
            ledger = FileTaskLedger(request.run_id)
            yield ledger.event("run.started", {"task": request.task, "mode": "file_task_v1", "model_mode": request.model_mode}, step_id="run")
            yield ledger.event("tool.finished", {"tool_name": "annotate_file", "success": True, "result_preview": "已写入批注意见。"}, step_id="annotation_write")
            yield ledger.event("file.changed", {"path": str(docx_path), "file_path": str(docx_path), "file_type": "docx", "operation": "annotate_file", "summary": f"已更新 {docx_path.name}。", "annotations_added": 2}, step_id="write")
            yield ledger.event("run.finished", {"summary": f"已更新 {docx_path.name}。", "completed_task": True, "mode": "file_task_v1"}, step_id="run")

        monkeypatch.setattr(bridge, "stream_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("task-stream must not call doc annotate bridge directly")))
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句，重新考虑中文翻译不当的部分或有复议可能性的用词或者替换成别的词的地方都标注出来。学术化翻译和中文学界常用词不对应的地方也标注出来，谨遵原著，不要有任何删减和添加。由于文件比较大内容比较多，我建议你将整个任务拆分成多个分段来处理，以保证最终结果的质量和任务可执行性",
                "session_id": "workspace_demo",
                "model_mode": "local",
                "model_id": "local",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert captured["request"].model_mode == "local"
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert any(event["type"] == "tool.finished" and event["payload"].get("tool_name") == "annotate_file" for event in events)
        assert run_finished["payload"]["completed_task"] is True

    def test_file_task_stream_followup_feedback_bypasses_doc_annotate_bridge(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskLedger
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        _write_minimal_docx(docx_path)

        captured = {}

        def fail_stream(request, **kwargs):
            raise AssertionError("doc annotate bridge should not handle review-last-task follow-up feedback")

        def fake_run(self, request):
            captured["request"] = request
            ledger = FileTaskLedger(request.run_id)
            yield ledger.event("run.started", {"task": request.task, "mode": "file_task_v1"}, step_id="run")
            yield ledger.event("run.finished", {"summary": "先反馈上一轮结果。", "completed_task": True, "mode": "file_task_v1"}, step_id="run")

        monkeypatch.setattr(bridge, "stream_request", fail_stream)
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "为什么你这次审校结果这么处理？",
                "session_id": "workspace_demo",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
                "options": {
                    "followup_context": {
                        "kind": "review_last_task",
                        "user_feedback": "为什么你这次审校结果这么处理？",
                        "previous_task_summary": "已生成带批注的审校稿 translation_revised.docx",
                    }
                },
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        run_finished = next(event for event in reversed(events) if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert captured["request"].options["followup_context"]["kind"] == "review_last_task"
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert run_finished["payload"]["completed_task"] is True

    def test_file_task_stream_followup_improve_routes_back_to_unified_file_task(self, app_client, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskLedger
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        _write_minimal_docx(docx_path)

        captured = {"request": None}

        def fake_run(self, request):
            captured["request"] = request
            ledger = FileTaskLedger(request.run_id)
            yield ledger.event("run.started", {"task": request.task, "mode": "file_task_v1"}, step_id="run")
            yield ledger.event("step_progress", {"detail": "已继续优化 1 处批注", "progress": 82, "file_updated": True, "path": str(docx_path), "file_path": str(docx_path), "supported": True}, step_id="annotation_write")
            yield ledger.event("tool.finished", {"tool_name": "annotate_file", "success": True, "result_preview": "已继续优化批注。"}, step_id="annotation_write")
            yield ledger.event("run.finished", {"summary": f"已继续优化 {docx_path.name}。", "completed_task": True, "mode": "file_task_v1"}, step_id="run")

        monkeypatch.setattr(bridge, "stream_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("task-stream must not call doc annotate bridge directly")))
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "请继续优化上一轮审校结果",
                "session_id": "workspace_demo",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
                "options": {
                    "followup_context": {
                        "kind": "review_last_task",
                        "followup_action": "improve",
                        "user_feedback": "请继续优化上一轮审校结果",
                        "previous_task_request": "根据原文审校这个译稿",
                        "previous_task_mode": "file_task_v1",
                    }
                },
            },
        )

        events = parse_sse_events(resp.get_data())
        run_started = next(event for event in events if event.get("type") == "run.started")
        run_finished = next(event for event in events if event.get("type") == "run.finished")

        assert resp.status_code == 200
        assert captured["request"].options["followup_context"]["followup_action"] == "improve"
        assert run_started["payload"]["mode"] == "file_task_v1"
        assert any(event["type"] == "tool.finished" and event["payload"].get("tool_name") == "annotate_file" for event in events)
        assert run_finished["payload"]["completed_task"] is True

    def test_doc_annotate_bridge_forwards_review_and_write_progress(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        _write_minimal_docx(docx_path)

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {"stage": "reading", "progress": 5, "message": "📖 正在读取文档", "detail": "解析Word文件结构"}
                yield {"stage": "reading_complete", "progress": 10, "message": "✅ 文档读取完成", "detail": "12 段，3000 字"}
                yield {"stage": "analyzing", "progress": 24, "message": "🤖 正在分析文档...", "detail": "第 1/5 段已完成，累计 2 条建议"}
                yield {"stage": "warning", "progress": 30, "message": "⚠️ AI 分析未成功（1/5分段使用本地规则兜底）", "detail": "API 错误: timeout"}
                yield {"stage": "analysis_complete", "progress": 50, "message": "✅ 分析完成", "detail": "找到 6 处修改"}
                yield {
                    "stage": "applying",
                    "progress": 78,
                    "message": "✏️ 正在写回 Word 修订",
                    "detail": "已写入 3/6 条修订",
                    "file_updated": True,
                    "path": str(docx_path),
                    "file_path": str(docx_path),
                    "supported": True,
                    "applied": 3,
                }
                yield {
                    "stage": "complete",
                    "progress": 100,
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 6,
                    },
                }

        monkeypatch.setattr(
            bridge,
            "_build_pdf_reference_windows",
            lambda path: (["[Page 1]\nOriginal source text"], {"window_count": 1, "page_count": 1, "window_pages": 4}),
        )
        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句，并标注可能需要复议的用词。",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        assert any(
            event.type == "step_progress"
            and event.step_id == "review"
            and "第 1/5 段已完成" in str(event.payload.get("detail") or "")
            for event in events
        )
        assert any(
            event.type == "step_progress"
            and event.step_id == "write"
            and "已写入 3/6 条修订" in str(event.payload.get("detail") or "")
            for event in events
        )
        assert any(
            event.type == "step_progress"
            and event.step_id == "write"
            and event.payload.get("file_updated") is True
            and event.payload.get("path") == str(docx_path)
            for event in events
        )
        file_changed = next(event for event in events if event.type == "file.changed")
        assert file_changed.payload["path"] == str(docx_path)
        assert file_changed.payload["file_path"] == str(docx_path)
        assert events[-1].type == "run.finished"
        assert events[-1].payload["completed_task"] is True

    def test_doc_annotate_bridge_handles_single_docx_annotation_requests(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "interview.docx"
        _write_minimal_docx(docx_path)

        captured_stream_kwargs = {}

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                captured_stream_kwargs.update(kwargs)
                yield {"stage": "reading", "progress": 5, "message": "📖 正在读取文档", "detail": "解析Word文件结构"}
                yield {"stage": "reading_complete", "progress": 10, "message": "✅ 文档读取完成", "detail": "21 段，553 字"}
                yield {"stage": "analyzing", "progress": 40, "message": "🤖 正在分析文档...", "detail": "已整理 10 条批注建议"}
                yield {"stage": "analysis_complete", "progress": 65, "message": "✅ 分析完成", "detail": "找到 10 处修改"}
                yield {
                    "stage": "applying",
                    "progress": 82,
                    "message": "✏️ 正在写回 Word 修订",
                    "detail": "已写入 6/10 条修订",
                    "file_updated": True,
                    "path": str(docx_path),
                    "file_path": str(docx_path),
                    "supported": True,
                    "applied": 6,
                }
                yield {
                    "stage": "complete",
                    "progress": 100,
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 10,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "将你觉得写得不好的地方批注出来",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(docx_path), "name": "interview.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        assert events[0].payload["mode"] == "annotate_file"
        assert events[0].payload["execution_mode"] == "docx_native_annotation"
        assert events[0].payload["executor"] == "Word 批注写回"
        plan_created = next(event for event in events if event.type == "plan.created")
        assert "正在审阅 Word 文档" in plan_created.payload["summary"]
        assert "文档批注路由" not in plan_created.payload["summary"]
        plan_briefed = next(event for event in events if event.type == "plan.briefed")
        assert plan_briefed.payload["title"] == "任务理解"
        assert "Word 批注" in plan_briefed.payload["summary"]
        assert plan_briefed.payload["executor"] == "Word 批注写回"
        assert captured_stream_kwargs["task_id"] == (request.task_id or request.run_id)
        assert callable(captured_stream_kwargs["cancel_check"])
        assert any(
            event.type == "tool.finished"
            and event.payload.get("tool_name") == "read_docx_content"
            and event.payload.get("path") == str(docx_path)
            for event in events
        )
        assert any(
            event.type == "step_progress"
            and event.step_id == "write"
            and "已写入 6/10 条修订" in str(event.payload.get("detail") or "")
            for event in events
        )
        file_changed = next(event for event in events if event.type == "file.changed")
        assert file_changed.payload["path"] == str(docx_path)
        assert file_changed.payload["file_path"] == str(docx_path)
        assert events[-1].type == "run.finished"
        assert events[-1].payload["completed_task"] is True

    def test_doc_annotate_bridge_treats_verified_no_change_docx_as_complete(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "humanise!_revised.docx"
        _write_minimal_docx(docx_path)

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {"stage": "reading_complete", "progress": 10, "message": "✅ 文档读取完成", "detail": "44 段，6447 字"}
                yield {"stage": "analysis_complete", "progress": 50, "message": "✅ 分析完成", "detail": "找到 0 处修改"}
                yield {
                    "stage": "complete",
                    "progress": 100,
                    "result": {
                        "success": True,
                        "message": "未找到修改点",
                        "original_file": str(docx_path),
                        "applied": 0,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)
        request = FileTaskRequest.from_mapping(
            {
                "task": "标注出文中你觉得写得不好/太像ai表达的部分",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(docx_path), "name": "humanise!_revised.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        assert not any(event.type == "file.changed" for event in events)
        check_finished = next(event for event in events if event.type == "check.finished")
        assert check_finished.payload["passed"] is True
        assert "保持不变" in check_finished.payload["summary"] or "核验可打开" in check_finished.payload["summary"]
        assert events[-1].type == "run.finished"
        assert events[-1].payload["completed_task"] is True

    def test_doc_annotate_bridge_fails_when_claimed_comments_are_missing_from_docx(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "draft.docx"
        _write_minimal_docx(docx_path)

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {"stage": "analysis_complete", "detail": "找到 1 处修改"}
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 1,
                        "annotation_output_mode": "comments",
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "直接在文本内加批注",
                "target_path": str(docx_path),
                "files": [{"path": str(docx_path), "name": "draft.docx", "type": "docx", "target": True}],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        check_finished = next(event for event in events if event.type == "check.finished")
        assert check_finished.payload["passed"] is False
        assert "未在 DOCX 内检测到对应的 Word 批注结构" in check_finished.payload["summary"]
        assert not any(event.type == "file.changed" for event in events)
        assert events[-1].payload["completed_task"] is False

    def test_doc_annotate_bridge_handles_dual_docx_compare_requests(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        target_docx = tmp_path / "humanise!_revised.docx"
        source_docx = tmp_path / "humanise!.docx"
        _write_minimal_docx(target_docx)
        _write_minimal_docx(source_docx)

        captured = {"reference_context": None, "user_requirement": "", "file_path": ""}

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, file_path, user_requirement="", model_id=None, reference_context="", **kwargs):
                captured["file_path"] = file_path
                captured["user_requirement"] = user_requirement
                captured["reference_context"] = reference_context
                yield {"stage": "reading_complete", "progress": 10, "message": "✅ 文档读取完成", "detail": "44 段，6448 字"}
                yield {"stage": "analysis_complete", "progress": 55, "message": "✅ 分析完成", "detail": "找到 11 处差异"}
                yield {
                    "stage": "applying",
                    "progress": 82,
                    "message": "✏️ 正在写回 Word 修订",
                    "detail": "已写入 8/11 条修订",
                    "file_updated": True,
                    "path": str(target_docx),
                    "file_path": str(target_docx),
                    "supported": True,
                    "applied": 8,
                }
                yield {
                    "stage": "complete",
                    "progress": 100,
                    "result": {
                        "success": True,
                        "revised_file": str(target_docx),
                        "applied": 11,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)
        monkeypatch.setattr(
            bridge,
            "_build_docx_reference_blocks",
            lambda path: (["[DOCX 片段 1]\n参考文档内容"], {"paragraph_count": 1, "window_count": 1}),
        )

        request = FileTaskRequest.from_mapping(
            {
                "task": "将两个docx文件内容有区别的地方在humanise!_revised.docx里面标注出来",
                "files": [
                    {"path": str(target_docx), "name": target_docx.name, "type": "docx"},
                    {"path": str(source_docx), "name": source_docx.name, "type": "docx"},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        run_started = next(event for event in events if event.type == "run.started")
        plan_created = next(event for event in events if event.type == "plan.created")
        reference_tool = next(event for event in events if event.type == "tool.finished" and event.step_id == "reference")
        file_changed = next(event for event in events if event.type == "file.changed")

        assert run_started.payload["target_path"] == str(target_docx)
        assert run_started.payload["source_path"] == str(source_docx)
        assert "正在对照两份 Word 文档" in plan_created.payload["summary"]
        assert reference_tool.payload["path"] == str(source_docx)
        assert captured["file_path"] == str(target_docx)
        assert isinstance(captured["reference_context"], list) and captured["reference_context"]
        assert "双 DOCX 差异对照任务" in captured["user_requirement"]
        assert target_docx.name in captured["user_requirement"]
        assert source_docx.name in captured["user_requirement"]
        assert file_changed.payload["path"] == str(target_docx)
        assert events[-1].type == "run.finished"
        assert events[-1].payload["completed_task"] is True

    def test_doc_annotate_bridge_marks_invalid_revised_docx_as_failed(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "broken-output.docx"
        docx_path.write_bytes(b"not-a-docx")

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 3,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "将你觉得写得不好的地方批注出来",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(docx_path), "name": "broken-output.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))
        check_finished = next(event for event in events if event.type == "check.finished")
        run_finished = next(event for event in events if event.type == "run.finished")

        assert check_finished.payload["passed"] is False
        assert check_finished.payload["status"] == "failed"
        assert "无法重新打开" in check_finished.payload["summary"]
        assert run_finished.payload["completed_task"] is False
        assert "无法重新打开" in run_finished.payload["summary"]
        assert not any(event.type == "file.changed" for event in events)

    def test_doc_annotate_bridge_merges_followup_improve_requirement(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest, FileTaskFile
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        docx_path.write_bytes(b"PK\x03\x04")

        captured = {}

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                captured["user_requirement"] = kwargs.get("user_requirement")
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 1,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)
        monkeypatch.setattr(
            bridge,
            "_build_pdf_reference_windows",
            lambda path: (["[Page 1]\nOriginal source text"], {"window_count": 1, "page_count": 1, "pages_with_text": 1, "window_pages": 4}),
        )

        request = FileTaskRequest(
            task="请继续优化上一轮审校结果",
            run_id="doc_bridge_followup_improve",
            target_path=str(docx_path),
            files=[
                FileTaskFile(path=str(pdf_path), name="source.pdf", type="pdf"),
                FileTaskFile(path=str(docx_path), name="translation.docx", type="docx", target=True),
            ],
            options={
                "followup_context": {
                    "kind": "review_last_task",
                    "followup_action": "improve",
                    "user_feedback": "请继续优化上一轮审校结果",
                    "previous_task_request": "根据原文审校这个译稿，给出学术化批注",
                    "previous_task_mode": "file_task_v1",
                }
            },
        )

        list(bridge.stream_request(request, workspace_root=str(tmp_path), gemini_client=object()))

        assert "上一轮任务要求：根据原文审校这个译稿，给出学术化批注" in captured["user_requirement"]
        assert "当前追加反馈：请继续优化上一轮审校结果" in captured["user_requirement"]

    def test_doc_annotate_bridge_enriches_single_docx_style_review_requirement(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "humanise!.docx"
        docx_path.write_bytes(b"PK\x03\x04")

        captured = {}

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                captured["user_requirement"] = kwargs.get("user_requirement")
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 2,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "把你觉得表达不通顺、像 AI 的地方标出来，并提出修改意见",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(docx_path), "name": docx_path.name, "type": "docx", "target": True},
                ],
            }
        )

        list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        assert "这是单个 DOCX 的中文表达体检任务" in captured["user_requirement"]
        assert "不要只挑极少数最显眼的问题" in captured["user_requirement"]
        assert "不要只给笼统批注" in captured["user_requirement"]

    def test_doc_annotate_bridge_emits_confirmed_batch_plan_for_large_files(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        monkeypatch.setenv("KOTO_DOC_REVIEW_CLOUD_BATCH_TARGET_MINUTES", "6")
        monkeypatch.setenv("KOTO_DOC_REVIEW_CLOUD_BATCH_CHARS_PER_MINUTE", "4000")

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        docx_path.write_bytes(b"PK\x03\x04")
        revised_path = tmp_path / "translation_revised.docx"

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"
            client = object()

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {"stage": "reading_complete", "detail": "539 段，100099 字"}
                yield {"stage": "analysis_complete", "detail": "找到 42 处修改"}
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(revised_path),
                        "applied": 42,
                    },
                }

            def _split_into_chunks_by_paragraphs(self, content, chunk_size):
                return [f"chunk-{idx}" for idx in range(27)]

        monkeypatch.setattr(
            bridge,
            "_build_pdf_reference_windows",
            lambda path: ([f"[Page {idx}]\ntext" for idx in range(1, 101)], {"window_count": 100, "page_count": 417, "pages_with_text": 399, "window_pages": 4}),
        )
        monkeypatch.setattr(
            bridge,
            "_inspect_docx_review_workload",
            lambda target_docx, feedback: {
                "paragraph_count": 539,
                "table_count": 2,
                "formatted_chars": 102901,
                "content_chars": 102801,
                "chunk_size": 4000,
                "chunk_count": 27,
            },
        )
        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句，并拆成多个分段来处理。",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))
        confirmed = next(event for event in events if event.type == "plan.confirmed")

        assert confirmed.step_id == "review"
        assert "按 5 批执行" in confirmed.payload["summary"]
        assert "约 2.4 万字/批" in confirmed.payload["summary"]
        assert confirmed.payload["steps"][0]["title"] == "第 1 批：分段 1-6"
        assert confirmed.payload["steps"][4]["title"] == "第 5 批：分段 25-27"
        assert confirmed.payload["steps"][-2]["title"] == "汇总并写回修订"
        assert "417 页" in confirmed.payload["note"]
        assert "539 段" in confirmed.payload["note"]
        assert "目标单批约 6 分钟" in confirmed.payload["note"]

    def test_large_translation_review_uses_finer_batches_in_local_mode(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        monkeypatch.setenv("KOTO_DOC_REVIEW_LOCAL_BATCH_TARGET_MINUTES", "5")
        monkeypatch.setenv("KOTO_DOC_REVIEW_LOCAL_BATCH_CHARS_PER_MINUTE", "2400")

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        docx_path.write_bytes(b"PK\x03\x04")

        revised_path = tmp_path / "translation_revised.docx"

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"
            client = object()

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {"stage": "reading_complete", "detail": "539 段，100099 字"}
                yield {"stage": "analysis_complete", "detail": "找到 42 处修改"}
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(revised_path),
                        "applied": 42,
                    },
                }

            def _split_into_chunks_by_paragraphs(self, content, chunk_size):
                return [f"chunk-{idx}" for idx in range(27)]

        monkeypatch.setattr(
            bridge,
            "_build_pdf_reference_windows",
            lambda path: ([f"[Page {idx}]\ntext" for idx in range(1, 101)], {"window_count": 100, "page_count": 417, "pages_with_text": 399, "window_pages": 4}),
        )
        monkeypatch.setattr(
            bridge,
            "_inspect_docx_review_workload",
            lambda target_docx, feedback: {
                "paragraph_count": 539,
                "table_count": 2,
                "formatted_chars": 102901,
                "content_chars": 102801,
                "chunk_size": 4000,
                "chunk_count": 27,
            },
        )
        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句，并拆成多个分段来处理。",
                "model_mode": "local",
                "model_id": "qwen3.5:9b",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))
        confirmed = next(event for event in events if event.type == "plan.confirmed")

        assert confirmed.step_id == "review"
        assert "按 9 批执行" in confirmed.payload["summary"]
        assert confirmed.payload["steps"][0]["title"] == "第 1 批：分段 1-3"
        assert confirmed.payload["steps"][8]["title"] == "第 9 批：分段 25-27"
        assert "约 1.2 万字/批" in confirmed.payload["summary"]
        assert "目标单批约 5 分钟" in confirmed.payload["note"]

    def test_local_docx_review_bridge_uses_local_model_identity(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "humanise!.docx"
        docx_path.write_bytes(b"PK\x03\x04")

        captured = {}

        class FakeFeedback:
            client = object()

            def __init__(self, gemini_client=None, default_model_id="gemini-2.5-pro"):
                captured["default_model_id"] = default_model_id
                self.gemini_client = gemini_client
                self.default_model_id = default_model_id

            def full_annotation_loop_streaming(self, *args, **kwargs):
                captured["stream_model_id"] = kwargs.get("model_id")
                yield {"stage": "reading_complete", "detail": "12 段，6300 字"}
                yield {
                    "stage": "analyzing",
                    "progress": 15,
                    "message": "分析中",
                    "detail": f"使用 AI({kwargs.get('model_id')}) 检查 12 段文本",
                }
                yield {"stage": "analysis_complete", "detail": "找到 8 处修改"}
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(docx_path),
                        "applied": 8,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "将文中不通顺和较为AI表达的地方标出来，并提出修改意见",
                "model_mode": "local",
                "model_id": "",
                "target_path": str(docx_path),
                "options": {"local_model": "qwen3.5:9b"},
                "files": [
                    {"path": str(docx_path), "name": docx_path.name, "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))

        review_progress = next(event for event in events if event.type == "step_progress")

        assert captured["default_model_id"] == "qwen3.5:9b"
        assert captured["stream_model_id"] == "qwen3.5:9b"
        assert "qwen3.5:9b" in review_progress.payload["detail"]

    def test_large_translation_review_cloud_mode_batches_by_char_budget(self, monkeypatch, tmp_path):
        from app.core.agent.file_task_contract import FileTaskRequest
        import app.core.agent.file_task_doc_annotate_bridge as bridge
        import web.document_feedback as feedback_module

        monkeypatch.setenv("KOTO_DOC_REVIEW_CLOUD_BATCH_TARGET_MINUTES", "6")
        monkeypatch.setenv("KOTO_DOC_REVIEW_CLOUD_BATCH_CHARS_PER_MINUTE", "4000")

        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        docx_path = tmp_path / "translation.docx"
        docx_path.write_bytes(b"PK\x03\x04")
        revised_path = tmp_path / "translation_revised.docx"

        class FakeFeedback:
            default_model_id = "gemini-2.5-pro"
            client = object()

            def __init__(self, gemini_client=None):
                self.gemini_client = gemini_client

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {"stage": "reading_complete", "detail": "160 段，104000 字"}
                yield {"stage": "analysis_complete", "detail": "找到 12 处修改"}
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(revised_path),
                        "applied": 12,
                    },
                }

        monkeypatch.setattr(
            bridge,
            "_build_pdf_reference_windows",
            lambda path: ([f"[Page {idx}]\ntext" for idx in range(1, 21)], {"window_count": 20, "page_count": 90, "pages_with_text": 84, "window_pages": 4}),
        )
        monkeypatch.setattr(
            bridge,
            "_inspect_docx_review_workload",
            lambda target_docx, feedback: {
                "paragraph_count": 160,
                "table_count": 0,
                "formatted_chars": 104120,
                "content_chars": 104000,
                "chunk_size": 4000,
                "chunk_count": 8,
                "chunk_char_counts": [20000, 4000, 4000, 20000, 4000, 4000, 24000, 24000],
            },
        )
        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        request = FileTaskRequest.from_mapping(
            {
                "task": "PDF是原文，docx文件是现有翻译稿。根据原文内容，润色翻译稿的语句，并拆成多个分段来处理。",
                "target_path": str(docx_path),
                "files": [
                    {"path": str(pdf_path), "name": "source.pdf", "type": "pdf"},
                    {"path": str(docx_path), "name": "translation.docx", "type": "docx", "target": True},
                ],
            }
        )

        events = list(bridge.stream_request(request, workspace_root=str(tmp_path)))
        confirmed = next(event for event in events if event.type == "plan.confirmed")

        assert confirmed.step_id == "review"
        assert "按 5 批执行" in confirmed.payload["summary"]
        assert "约 2.4 万字/批" in confirmed.payload["summary"]
        assert confirmed.payload["steps"][0]["title"] == "第 1 批：分段 1-2"
        assert confirmed.payload["steps"][1]["title"] == "第 2 批：分段 3-4"
        assert confirmed.payload["steps"][2]["title"] == "第 3 批：分段 5-6"
        assert confirmed.payload["steps"][3]["title"] == "第 4 批：分段 7-7"
        assert confirmed.payload["steps"][4]["title"] == "第 5 批：分段 8-8"
        assert "预计用时约 6 分钟" in confirmed.payload["steps"][0]["description"]
        assert "目标单批约 6 分钟" in confirmed.payload["note"]

    def test_build_pdf_reference_windows_keeps_all_windows_by_default(self, monkeypatch):
        import app.core.agent.file_task_doc_annotate_bridge as bridge

        fake_pages = [
            {"page": idx, "text": f"Page {idx} text"}
            for idx in range(1, 10)
        ]

        with patch("app.core.file.file_parser.parse_pdf", return_value={"page_count": 9, "pages": fake_pages, "text": ""}):
            windows, meta = bridge._build_pdf_reference_windows("dummy.pdf", window_pages=4, per_window_chars=1000)

        assert len(windows) == 3
        assert meta["page_count"] == 9
        assert meta["pages_with_text"] == 9
        assert meta["window_count"] == 3
        assert "[Page 9]" in windows[-1]

    def test_file_task_stream_normalizes_local_model_config(self, app_client, monkeypatch):
        from app.core.agent.file_task_contract import FileTaskEvent
        from app.core.agent.file_task_runtime import FileTaskRuntime

        captured = {}

        def fake_run(self, request):
            captured["request"] = request
            yield FileTaskEvent(
                type="run.finished",
                run_id=request.run_id,
                seq=1,
                payload={"summary": "ok", "completed_task": True},
            )

        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        with patch("web.app._get_configured_local_model_id", return_value="qwen3.5:9b"):
            resp = app_client.post(
                "/api/editor/ai/task-stream",
                json={
                    "task": "总结当前文件",
                    "model_mode": "local",
                    "model_id": "gemini-3-flash-preview",
                },
            )

        request_payload = captured["request"]
        assert resp.status_code == 200
        assert request_payload.model_mode == "local"
        assert request_payload.model_id == ""
        assert request_payload.options["local_model"] == "qwen3.5:9b"

    def test_file_task_stream_keeps_finished_run_runtime_only(self, app_client, monkeypatch):
        from app.core.agent.file_task_contract import FileTaskEvent
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import web.app as web_app_module

        calls = {"save": 0, "extract": 0}

        def fake_run(self, request):
            yield FileTaskEvent(
                type="file.changed",
                run_id=request.run_id,
                seq=1,
                step_id="execute",
                payload={"path": "report.docx", "operation": "write_docx_content", "summary": "已写入"},
            )
            yield FileTaskEvent(
                type="run.finished",
                run_id=request.run_id,
                seq=2,
                payload={"summary": "已完成文件任务", "completed_task": True},
            )

        def fake_append(*args, **kwargs):
            calls["save"] += 1
            return []

        def fake_memory(*args, **kwargs):
            calls["extract"] += 1

        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)
        monkeypatch.setattr(web_app_module.session_manager, "append_and_save", fake_append)
        monkeypatch.setattr(web_app_module, "_start_memory_extraction", fake_memory)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={"task": "把总结写入当前文件", "session_id": "workspace_demo"},
        )
        events = parse_sse_events(resp.get_data())

        assert resp.status_code == 200
        assert any(event.get("type") == "run.finished" for event in events)
        assert events[-1]["type"] == "ui.message"
        assert events[-1]["payload"]["raw_type"] == "run.finished"
        assert not any(event.get("type") == "memory.loaded" for event in events)
        assert calls == {"save": 0, "extract": 0}

    def test_file_task_stream_uses_request_history_only(self, app_client, monkeypatch):
        from app.core.agent.file_task_contract import FileTaskEvent
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import web.app as web_app_module

        captured = {"loaded": []}

        def fake_load(filename):
            captured["loaded"].append(filename)
            return [
                {"role": "user", "parts": ["上一次任务"]},
                {"role": "model", "parts": ["上一次结果"]},
            ]

        def fake_run(self, request):
            captured["request"] = request
            yield FileTaskEvent(
                type="run.finished",
                run_id=request.run_id,
                seq=1,
                payload={"summary": "本轮完成", "completed_task": True},
            )

        monkeypatch.setattr(web_app_module.session_manager, "load", fake_load)
        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={
                "task": "继续处理当前文件",
                "session_id": "workspace_demo",
                "history": [
                    {"role": "user", "content": "前端短期任务"},
                    {"role": "assistant", "content": "前端短期结果"},
                    {"role": "user", "content": "继续处理当前文件"},
                ],
            },
        )
        resp.get_data()

        request_payload = captured["request"]
        assert resp.status_code == 200
        assert captured["loaded"] == []
        assert request_payload.history == [
            {"role": "user", "content": "前端短期任务"},
            {"role": "assistant", "content": "前端短期结果"},
            {"role": "user", "content": "继续处理当前文件"},
        ]

    def test_file_task_stream_does_not_inject_memory_router_context(self, app_client, monkeypatch):
        from app.core.agent.file_task_contract import FileTaskEvent
        from app.core.agent.file_task_runtime import FileTaskRuntime
        import web.app as web_app_module

        captured = {}

        def fake_run(self, request):
            captured["request"] = request
            yield FileTaskEvent(
                type="run.finished",
                run_id=request.run_id,
                seq=1,
                payload={"summary": "完成", "completed_task": True},
            )

        monkeypatch.setattr(FileTaskRuntime, "run", fake_run)
        monkeypatch.setattr(web_app_module, "get_memory_manager", lambda: (_ for _ in ()).throw(AssertionError("memory manager should not be used")))

        resp = app_client.post(
            "/api/editor/ai/task-stream",
            json={"task": "整理当前 Word 文档", "session_id": "workspace_demo", "file_name": "report.docx"},
        )
        events = parse_sse_events(resp.get_data())

        request_payload = captured["request"]
        assert resp.status_code == 200
        assert not any(event.get("type") == "memory.loaded" for event in events)
        assert "memory_context" not in (request_payload.options or {})

    def test_file_task_summary_context_injection_preserves_file_path_order(self):
        from web.app import _inject_recent_file_task_summary_context

        captured = {}
        payload = {
            "files": [
                {"path": "beta.docx"},
                {"path": "alpha.docx"},
                {"path": "beta.docx"},
            ],
            "target_path": "target.docx",
            "options": {},
        }

        def fake_load_recent_summaries(file_paths, limit=5):
            captured["file_paths"] = list(file_paths)
            captured["limit"] = limit
            return [{"summary": "recent summary"}]

        def fake_format_summaries_as_context(recent):
            captured["recent"] = list(recent)
            return "最近任务摘要"

        result = _inject_recent_file_task_summary_context(
            payload,
            load_recent_summaries_fn=fake_load_recent_summaries,
            format_summaries_as_context_fn=fake_format_summaries_as_context,
        )

        assert captured["file_paths"] == ["beta.docx", "alpha.docx", "target.docx"]
        assert captured["limit"] == 5
        assert captured["recent"] == [{"summary": "recent summary"}]
        assert result["options"]["memory_context"] == "最近任务摘要"

    def test_editor_ai_history_is_empty_for_runtime_only_conversations(self, app_client, monkeypatch):
        import web.app as web_app_module

        loaded = []

        def fake_load_full(filename):
            loaded.append(filename)
            return []

        monkeypatch.setattr(web_app_module.session_manager, "load_full", fake_load_full)

        resp = app_client.get("/api/editor/ai/history?session_id=workspace_demo&doc_id=demo")
        data = resp.get_json()

        assert resp.status_code == 200
        assert loaded == []
        assert data == {"history": [], "session_id": ""}

    def test_file_task_runtime_includes_memory_context_in_task_prompt(self):
        from app.core.agent.file_task_contract import FileTaskRequest
        from app.core.agent.file_task_runtime import FileTaskRuntime

        runtime = FileTaskRuntime(tool_executor=lambda name, args: "")
        request_payload = FileTaskRequest(
            task="总结文档",
            options={"memory_context": "用户偏好：保留原文格式。"},
        )

        messages = runtime._build_messages(request_payload, [], [])

        assert "memory_context" in messages[-1]["content"]
        assert "保留原文格式" in messages[-1]["content"]

    def test_workspace_open_file_returns_temp_path(self, app_client):
        resp = app_client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO("hello world".encode("utf-8")), "notes.txt")},
            content_type="multipart/form-data",
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["temp_path"].startswith("tmp/")
        assert data["temp_path"].endswith(".txt")

    def test_main_stream_forwards_plan_and_step_events(self, app_client):
        """The retired editor stream should no longer expose legacy plan/step SSE behavior."""
        self._assert_editor_ai_stream_removed(
            app_client,
            {
                "action": "polish",
                "selection": "这段文字需要润色。",
            },
        )

    def test_main_stream_keeps_editor_actions_runtime_only(self, app_client, monkeypatch):
        """The retired editor stream should reject session-bound runtime-only editor actions."""
        self._assert_editor_ai_stream_removed(
            app_client,
            {
                "action": "polish",
                "selection": "这段文字需要润色。",
                "session_id": "workspace_demo",
                "history": [
                    {"role": "user", "content": "先润色标题"},
                    {"role": "assistant", "content": "标题已经润色"},
                ],
            },
        )

    def test_non_task_stream_passes_preferred_and_local_model_into_agent_request(self, app_client):
        """The retired editor stream should reject model-selection requests before legacy AgentLoop setup."""
        self._assert_editor_ai_stream_removed(
            app_client,
            {
                "action": "polish",
                "selection": "这段文字需要润色。",
                "model_mode": "cloud",
                "model_id": "gemini-2.5-pro",
            },
        )


class TestEditorAIAgent:
    """Tests for POST /api/editor/ai/agent structured progress events."""

    def test_agent_route_emits_structured_step_events(self, app_client):
        from app.core.agent.types import AgentAction, AgentStep, AgentStepType

        class FakeAgent:
            def run(self, input_text, session_id=None, system_context=None):
                yield AgentStep(step_type=AgentStepType.THOUGHT, content="先理解文档问题")
                yield AgentStep(
                    step_type=AgentStepType.ACTION,
                    content="执行搜索",
                    action=AgentAction(tool_name="web_search", tool_args={"query": "AI"}),
                )
                yield AgentStep(
                    step_type=AgentStepType.OBSERVATION,
                    content="找到结果",
                    observation="找到 3 条相关结果",
                )
                yield AgentStep(step_type=AgentStepType.ANSWER, content="最终答案")

        with patch("app.api.agent_routes.get_agent", return_value=FakeAgent()):
            resp = app_client.post(
                "/api/editor/ai/agent",
                json={"query": "帮我分析这份文档", "full_text": "文档内容"},
            )
            payload = resp.get_data()

        assert resp.status_code == 200
        events = parse_sse_events(payload)
        types = [e.get("type") for e in events]
        assert "thought" in types
        assert "step_start" in types
        assert "tool_call" in types
        assert "tool_result" in types
        assert "step_done" in types
        assert "token" in types
        assert "done" in types


class TestChartStream:
    """Tests for the removed chart side-channel."""

    def test_chart_stream_endpoint_is_removed(self, app_client):
        resp = app_client.post(
            "/api/editor/ai/chart",
            json={"data_context": "类别,值\nA,10", "instruction": "画一个简单图表", "lang": "python"},
        )

        assert resp.status_code == 404


class TestLocalModelMode:
    """Tests that legacy editor stream is no longer available."""

    def test_local_mode_uses_ollama_when_alive(self, app_client):
        """The removed editor stream should not accept local or cloud requests."""
        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "polish",
            "selection": "需要润色的文字",
            "model_mode": "local",
        })

        assert resp.status_code == 404

        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "polish",
            "selection": "需要润色的文字",
            "model_mode": "local",
        })

        assert resp.status_code == 404

        resp = app_client.post("/api/editor/ai/stream", json={
            "action": "polish",
            "selection": "需要润色的文字",
            "model_mode": "cloud",
        })

        assert resp.status_code == 404

    def test_workspace_quick_actions_use_file_task_only_and_do_not_keep_editor_stream_fallback(self):
        """Workspace quick actions should route only through the file-task path and must not retain the legacy editor SSE fallback."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        assert "window.WA.sendQuickAction = (action) => {" in src
        assert "window.WA.createWorkspaceQuickActionRuntime" in quick_actions
        assert "attachDispatcher" in quick_actions
        assert "return Promise.reject(new Error(`快捷动作 ${actionId} 未配置可用的执行路径`));" in quick_actions
        assert "if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {" in quick_actions
        assert "/api/editor/ai/stream" not in quick_actions
        assert "sendEditorAction(" not in quick_actions
        assert "return attachedDispatcher.dispatchMessage({" in quick_actions

    def test_workspace_readonly_quick_actions_can_use_simple_file_task(self):
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")

        assert "fileTaskMode: 'simple'" in quick_actions
        assert "function usesSimpleFileTask(action) {" in quick_actions
        assert "function sendSimpleFileTaskAction(payload, providedAction) {" in quick_actions
        assert "return attachedDispatcher.dispatchMessage({" in quick_actions
        assert "quick_action_mode: 'simple'" in quick_actions

    def test_workspace_edit_quick_actions_can_use_proposal_file_task(self):
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")

        assert "fileTaskMode: 'proposal'" in quick_actions
        assert "function usesProposalFileTask(action) {" in quick_actions
        assert "function buildProposalFileTask(payload, action) {" in quick_actions
        assert "function sendProposalFileTaskAction(payload, providedAction) {" in quick_actions
        assert "quick_action_mode: 'proposal'" in quick_actions
        assert "options.handleProposals({" in quick_actions
        assert "sendEditorAction(" not in quick_actions

    def test_workspace_model_state_uses_wa_keys_only(self):
        """Workspace assistant should use wa_* model state only and not write legacy editor_* keys."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        toggle_start = src.find("window.WA.setUseLocalModel = (useLocal) => {")
        toggle_end = src.find("window.WA.setLockedModel = (val) => {", toggle_start)
        assert toggle_start != -1 and toggle_end != -1
        toggle_section = src[toggle_start:toggle_end]
        assert "function _syncEditorModelPreference(" not in src
        assert "editor_model_mode" not in src
        assert "editor_locked_model" not in src
        assert "localStorage.setItem('wa_locked_model', newModel);" in toggle_section
        assert "localStorage.setItem('wa_model_choice_explicit', '1');" in toggle_section

    def test_workspace_chart_requests_delegate_to_file_task_dispatcher_without_legacy_dialog_helper(self):
        """Chart quick actions should route through the file-task dispatcher after the retired chart dialog helper is removed."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        assert "async function _sendViaLegacyChartSSE(payload) {" not in src
        assert "async function _sendViaSSEChart(payload) {" not in src
        assert "window.WA.openChartDialog = (lang) => {" not in src
        assert "window.WA.submitChartRequest = () => {" not in src
        assert "fetch('/api/editor/ai/chart'" not in src
        assert "attachedDispatcher.dispatchMessage({" in quick_actions
        assert "url: '/api/editor/ai/chart'" not in quick_actions
        assert "model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : 'cloud'," in dispatcher
        assert "model_id: typeof options.getSelectedCloudModelId === 'function' ? options.getSelectedCloudModelId() : ''," in dispatcher

    def test_workspace_task_renderer_supports_python_artifacts(self):
        """The file-task renderer should render image artifacts emitted by run_python_code."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        assert "function appendToolArtifacts(row, payload)" in renderer
        assert "payload.artifacts" in renderer
        assert "wa-task-artifact-image" in renderer

    def test_workspace_task_renderer_distinguishes_blocked_python_calls(self):
        """Blocked run_python_code guidance should be labeled as an interception reason, not Python output."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        assert "if (type === 'tool.blocked')" in renderer
        assert "策略拦截：${toolLabel(payload.tool_name)}" in renderer
        assert "查看拦截说明" in renderer
        assert "payload.blocked ? '查看拦截原因' : '查看执行输出'" in renderer
        assert "const blocked = !!payload.blocked;" in renderer
        assert "const chipText = blocked ? '拦截'" in renderer

    def test_workspace_task_renderer_hides_model_facing_tool_and_code_details(self):
        """Task cards should keep tool proposals and generated code summaries user-facing instead of exposing raw model payloads."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function renderToolArgs(payload) {" not in renderer
        assert "查看建议工具设计" not in renderer
        assert "实现代码（" not in renderer
        assert "<summary>参数</summary>" not in renderer
        assert "拟调用" not in renderer
        assert "查看 Python 代码" not in renderer
        assert "所需处理能力已就绪" in renderer
        assert "<span class=\"wa-task-chip\">准备</span>" in renderer
        assert "正在执行 Python 处理" in renderer

    def test_workspace_task_renderer_hides_internal_followup_ids_and_model_request_metadata(self):
        """Task cards should not expose internal follow-up ids or model-requested sheet metadata."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "工具待办：" not in renderer
        assert "模型请求：" not in renderer
        assert "后续事项：${esc(statusLabel)}" in renderer
        assert "来源文件：${esc(sourceName)}" in renderer

    def test_workspace_task_renderer_eagerly_refreshes_changed_files(self):
        """Segmented file tasks should try to refresh the edited document as soon as file.changed arrives."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        refresh = Path("web/static/js/workspace-ai-task-refresh.js").read_text(encoding="utf-8")
        assert "card._fileRefreshPromise" in refresh
        assert "function triggerQueuedFileRefresh(card, options) {" in renderer
        assert "void flush(card)" in refresh
        assert "console.warn(errorLog, err);" in refresh
        assert "queueTerminalFileChanges(card, payload || {});" in renderer
        assert "if (!((card._pendingFileRefreshes && card._pendingFileRefreshes.size) || card._fileRefreshPromise)) return false;" in refresh
        assert "function upsertEntry(card, item)" in refresh
        assert "payload.path || payload.file_path || payload.output_path || payload.target_path" in refresh
        assert "['pending', 'refreshing', 'reloaded'].includes(previousStatus)" in refresh
        assert "status: supported ? 'pending' : 'unsupported'" in refresh
        assert "status: 'refreshing'" in refresh
        assert "status: 'reloaded'" in refresh
        assert "status: 'failed'" in refresh

    def test_workspace_task_renderer_keeps_write_tool_milestones_visible(self):
        """Successful file-writing tool events should remain visible instead of being fully suppressed."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "return isInternalTool(name) || isReadTool(name);" in renderer
        assert "return false;" in renderer
        assert "toolStepTitle(payload.tool_name)" in renderer
        assert "setStepTitle(step, blocked ? `${toolLabel(payload.tool_name)}已拦截`" in renderer

    def test_workspace_task_renderer_summarizes_refresh_state_in_final_card(self):
        """The final task summary should include per-file refresh state so stale documents are visible to the user."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        refresh = Path("web/static/js/workspace-ai-task-refresh.js").read_text(encoding="utf-8")

        assert "function fileRefreshSummaryHtml(card)" in renderer
        assert "statusLabel(entry.status)" in refresh
        assert "const refreshHtml = fileRefreshSummaryHtml(card);" in renderer
        assert "${refreshHtml}${runtimeHtml}" in renderer
        assert "策略：${esc(payload.accent_style)}" in renderer
        assert "变化：${esc(payload.visual_change_score)}" in renderer

    def test_workspace_task_renderer_warns_when_file_task_stream_seq_is_incomplete(self):
        """Dropped or replayed SSE events should be merged without turning the task into a failure."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function noteStreamIssue(card, key, text)" in renderer
        assert "state.streamIssueKeys" in renderer
        assert "state.streamIssueRow" in renderer
        assert "state.lastEventSeq" in renderer
        assert "processedEventKeys: new Set()" in renderer
        assert "function hydrateTaskUiStateFromDom(card, state)" in renderer
        assert "if (!(state.multiTargetActive && type === 'run.finished'))" in renderer
        assert "state.domHydrated = true;" in renderer
        assert "row.dataset.role = `model:${key}`;" in renderer
        assert "row.dataset.role = `read:${key}`;" in renderer
        assert "检测到部分进度事件未按顺序抵达，已自动整理当前可见过程。" in renderer
        assert "检测到任务进度事件重放，已自动合并重复更新。" in renderer
        assert "任务事件流缺失了" not in renderer
        assert "任务事件流顺序异常" not in renderer

    def test_workspace_task_renderer_supports_step_result_rollups(self):
        """The renderer should display backend step.result rollups for major FileTask phases."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function renderStepResult(payload)" in renderer
        assert "function upsertStepResultRow(step, payload)" in renderer
        assert "type === 'step.result'" in renderer
        assert "const changeCount = Number(payload.file_change_count" in renderer
        assert "if (changeCount <= 1) return '';" in renderer
        assert "查看文件变更" not in renderer

    def test_workspace_task_renderer_supports_step_progress_updates(self):
        """The FileTask task renderer should keep the current step alive with incremental progress updates."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function upsertProgressRow(step, payload)" in renderer
        assert "type === 'step_progress' || type === 'step.progress'" in renderer
        assert "step._progressRow" in renderer
        assert "payload.file_updated || payload.fileUpdated" in renderer
        assert "queueFileRefresh(card, payload, {" in renderer
        assert "stepTitle: '写入文件'" in renderer
        assert "triggerQueuedFileRefresh(card, {" in renderer

    def test_workspace_task_renderer_marks_estimated_progress_as_non_explicit(self):
        """Lifecycle-only task states should not display fake exact percentages."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        styles = Path("web/static/css/workspace.css").read_text(encoding="utf-8")

        assert "progress_explicit === true" in renderer
        assert "data-role=\"ui-progress-value\">准备中" in renderer
        assert "? `${progress}%`" in renderer
        assert ": (progress > 0 ? '执行中' : '准备中')" in renderer
        assert 'progressEl.dataset.explicit = hasExplicitProgress ?' in renderer
        assert '.wa-task-progress[data-explicit="false"]' in styles

    def test_workspace_task_renderer_surfaces_idle_file_task_heartbeat(self):
        """Long model/tool gaps should be visible instead of looking stuck."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "const FILE_TASK_IDLE_NOTICE_MS = 25000;" in renderer
        assert "const FILE_TASK_IDLE_WARN_MS = 60000;" in renderer
        assert "function startTaskHeartbeat(card)" in renderer
        assert "function stopTaskHeartbeat(card)" in renderer
        assert "任务仍在后台执行；本地模型或大文件处理可能需要更久。" in renderer
        assert "startTaskHeartbeat(card);" in renderer
        assert "stopTaskHeartbeat(card);" in renderer

    def test_workspace_task_renderer_preserves_structured_run_errors(self):
        """Structured run.error messages should survive transport failures instead of collapsing to generic network errors."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "function makeTaskError(message) {" in renderer
        assert "const fatalText = payload.text || payload.error || '任务失败';" in renderer
        assert "applyTerminalPayload(card, evt, payload, {" in renderer
        assert "fatalText," in renderer
        assert "if (card._fatalErrorText) throw makeTaskError(card._fatalErrorText);" in renderer
        assert "error && error.waTaskError ? error.message" in dispatcher

    def test_workspace_task_renderer_surfaces_runtime_metadata(self):
        """The task renderer should expose runtime execution metadata from FileTask SSE terminal events."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        status = Path("web/static/js/workspace-ai-task-status.js").read_text(encoding="utf-8")

        assert "function runtimeExecutionLabel(runtime) {" in renderer
        assert "function runtimeMetaHtml(payload) {" in renderer
        assert "function finalRunStatusText(payload) {" in renderer
        assert "状态：" in renderer
        assert "已改用摘要结果" in renderer
        assert "return '待确认';" in status
        assert "return '等待确认';" in renderer
        assert "return '缺少工具';" in status
        assert "return '摘要回退';" in status
        assert "planner_fallback" not in status
        assert "statusText: finalRunStatusText(payload)," in renderer
        assert 'chips.push(`执行：${executionLabel}`);' not in renderer
        assert 'chips.push(`结果：${terminalLabel}`);' not in renderer

        tool_gap_start = renderer.find("function renderToolGap(evt) {")
        tool_gap_end = renderer.find("function renderFollowupRecord(record) {", tool_gap_start)
        run_summary_start = renderer.find("function renderRunSummary(payload, card) {")
        run_summary_end = renderer.find("function renderFileChange(evt) {", run_summary_start)
        check_finished_start = renderer.find("if (type === 'check.finished') {")
        check_finished_end = renderer.find("if (type === 'step.finished') {", check_finished_start)

        assert tool_gap_start != -1 and tool_gap_end != -1
        assert run_summary_start != -1 and run_summary_end != -1
        assert check_finished_start != -1 and check_finished_end != -1
        assert "runtimeMetaHtml(payload)" in renderer[tool_gap_start:tool_gap_end]
        assert "runtimeExecutionLabel(artifact.runtime_context)" not in renderer[tool_gap_start:run_summary_end]
        assert "runtimeMetaHtml(payload)" in renderer[run_summary_start:run_summary_end]
        assert "runtimeMetaHtml(payload)" in renderer[check_finished_start:check_finished_end]

    def test_workspace_task_renderer_surfaces_task_classification_metadata(self):
        """The FileTask task renderer should persist classification metadata from run lifecycle events."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "function normalizedTaskLifecyclePayload(payload) {" in renderer
        assert "const classification = data.classification && typeof data.classification === 'object'" in renderer
        assert "if (type === 'task.classified') {" in renderer
        assert "const rendered = renderTaskClassification(evt, card);" in renderer
        assert "function classificationMetaHtml(card) {" in renderer
        assert "function renderTaskClassification(evt, card) {" in renderer
        assert "const data = normalizedTaskLifecyclePayload(payload);" in renderer
        assert "card.dataset.taskRequestKind = String(data.request_kind || '').trim();" in renderer
        assert "card.dataset.taskFamily = String(data.task_family || '').trim();" in renderer
        assert "card.dataset.taskOutputMode = String(data.output_mode || '').trim();" in renderer
        assert "card.dataset.taskIntentStrategy = intentStrategy;" in renderer
        assert "card.dataset.taskIntentCanApply = intentPlan.can_apply ? 'true' : 'false';" in renderer
        assert "card.dataset.taskIntentRequiresConfirmation = intentPlan.requires_confirmation ? 'true' : 'false';" in renderer
        assert "if (type === 'run.started') {" in renderer
        assert "if (type === 'run.finished') {" in renderer
        assert "产出：" in renderer
        assert "策略：" in renderer
        assert "后续：" in renderer
        assert "目标：" in renderer
        assert 'chips.push(`请求：${requestLabel}`);' not in renderer
        assert 'chips.push(`任务：${familyLabel}`);' not in renderer
        assert 'chips.push(`操作：${operationLabel}`);' not in renderer
        assert 'chips.push(`分类：${executionLabel}`);' not in renderer
        assert "${classificationHtml}${refreshHtml}${runtimeHtml}" in renderer

        assert "if (dataset.taskRequestKind) metadata.task_request_kind = String(dataset.taskRequestKind || '').trim();" in dispatcher
        assert "if (dataset.taskFamily) metadata.task_family = String(dataset.taskFamily || '').trim();" in dispatcher
        assert "if (dataset.taskExecutionMode) metadata.task_execution_mode = String(dataset.taskExecutionMode || '').trim();" in dispatcher
        assert "if (dataset.taskOutputMode) metadata.task_output_mode = String(dataset.taskOutputMode || '').trim();" in dispatcher
        assert "if (dataset.taskIntentStrategy) metadata.task_intent_strategy = String(dataset.taskIntentStrategy || '').trim();" in dispatcher
        assert "metadata.task_intent_can_apply = String(dataset.taskIntentCanApply || '').trim().toLowerCase() === 'true';" in dispatcher
        assert "metadata.task_intent_requires_confirmation = String(dataset.taskIntentRequiresConfirmation || '').trim().toLowerCase() === 'true';" in dispatcher
        assert "const taskVisibleTrace = taskCardVisibleTrace(loadingEl);" in dispatcher
        assert "if (taskVisibleTrace) metadata.task_visible_trace = taskVisibleTrace;" in dispatcher

    def test_workspace_task_renderer_labels_answer_and_hybrid_output_modes(self):
        """Answer-first and hybrid file tasks should show explicit non-write guidance in the task card."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "if (normalized === 'answer') return '只给答案';" in renderer
        assert "if (normalized === 'write') return '写入文件';" in renderer
        assert "if (normalized === 'hybrid') return '先分析后决定';" in renderer
        assert "本轮只做分析，未写入文件。" in renderer
        assert "本轮先完成分析；确认后可写入文件。" in renderer
        assert "本轮完成分析，未写入文件。" in renderer
        assert 'data-task-followup-action="apply"' in renderer
        assert "应用建议" in renderer
        assert "if (outputMode === 'hybrid' && canApply) chips.push(`后续：${requiresConfirmation ? '确认后可写入' : '可继续写入'}`);" in renderer
        assert "const previousTaskOutputMode = previewText(previousTaskTurn.task_output_mode || '', 120);" in dispatcher
        assert "if (previousTaskOutputMode) context.previous_task_output_mode = previousTaskOutputMode;" in dispatcher

    def test_workspace_task_renderer_treats_awaiting_confirmation_as_paused_not_failed(self):
        """Paused step-confirmation runs should render as waiting-for-confirmation, not as failures."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "if (status === 'awaiting_confirmation') return '等待确认';" in renderer
        assert "if (terminalStatus === 'awaiting_confirmation') return '待确认';" in renderer
        assert "const awaitingConfirmation = status === 'awaiting_confirmation';" in renderer
        assert "if (status === 'awaiting_confirmation') return 'awaiting_confirmation';" in renderer
        assert "if (status === 'awaiting_confirmation') return '待确认';" in renderer
        assert "} else if (status === 'awaiting_confirmation' || status === 'needs_attention' || status === 'pending') {" in renderer
        assert "step.classList.add('pending');" in renderer
        assert "const chipText = ok ? '通过' : (awaitingConfirmation ? '待确认' : '未完成');" in renderer
        assert "function finalRunStatusTextWithRefresh(payload, refreshOk) {" in renderer
        assert "return base ? `${base}，刷新失败` : '刷新失败';" in renderer
        assert "setStatus(card, finalRunStatusTextWithRefresh(payload, refreshOk));" in renderer

    def test_workspace_task_renderer_deduplicates_batch_confirmation_resume_prompt(self):
        """Batch confirmation cards should keep one visible resume CTA instead of duplicating inline spec details and buttons."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "已完成当前步骤，确认后继续下一步。" in renderer
        assert "const category = String(artifact.category || '').trim().toLowerCase();" in renderer
        assert "const detailHtml = (category && category === 'batch_confirmation') || !details.length" in renderer
        assert "const resumeActionHtml = category === 'batch_confirmation' ? '' : renderResumeArtifactAction(artifact);" in renderer
        assert "当前任务停在待确认批次，点击按钮即可继续执行下一步。" not in renderer

    def test_workspace_task_renderer_shows_next_step_cta_for_pending_resume_payload(self):
        """Stepwise tasks should expose a direct next-step CTA whenever a resume payload is available."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "const waitingForContinuation = terminalStatus === 'awaiting_confirmation'" in renderer
        assert "|| terminalStatus === 'needs_attention'" in renderer
        assert "|| terminalStatus === 'pending'" in renderer
        assert "|| !completed;" in renderer
        assert "if (pendingResumePayload && waitingForContinuation)" in renderer
        assert "const actionLabel = pendingResumeLabel || '继续下一步';" in renderer

    def test_workspace_task_renderer_surfaces_inherited_stepwise_resume_context(self):
        """Follow-up cards should show that they still inherit the paused stepwise resume payload."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function isConfirmEachStepResumePayload(payload) {" in renderer
        assert "function originalTaskLabelFromResumePayload(payload) {" in renderer
        assert "function inheritedStepwiseResumeMetaHtml(card) {" in renderer
        assert "const existingResumePayload = decodeTaskRequestPayload(card.dataset.taskPendingResumePayload || '');" in renderer
        assert "if (!isConfirmEachStepResumePayload(existingResumePayload)) {" in renderer
        assert "if (terminalStatus === 'awaiting_confirmation') return '';" in renderer
        assert "const match = taskText.match(/原始任务[：:]\\s*(.+)$/u);" in renderer
        assert "chips.push(`沿用分步任务：${inheritedTask || '继续下一步'}`);" in renderer
        assert "if (Number.isFinite(stepIndex) && stepIndex > 0) chips.push(`步骤：${stepIndex}`);" in renderer
        assert "const pendingResumeHtml = inheritedStepwiseResumeMetaHtml(card);" in renderer
        assert "${classificationHtml}${pendingResumeHtml}${refreshHtml}${runtimeHtml}${nextActionArtifact}${taskResultActionsHtml(card)}" in renderer

    def test_workspace_task_renderer_normalizes_plan_check_copy(self):
        """Plan-check rows should not repeat the same '规划检查' prefix in both chip and summary text."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function normalizedPlanCheckSummary(summary, passed) {" in renderer
        assert "const normalized = text.replace(/^规划检查(?:通过|未通过)?[：:]?\\s*/u, '').trim();" in renderer
        assert "const chip = passed ? '<span class=\"wa-task-chip ok\">通过</span>' : '<span class=\"wa-task-chip error\">未通过</span>';" in renderer
        assert '<span class="wa-task-chip ok">规划检查</span>' not in renderer
        assert '<span class="wa-task-chip error">规划检查</span>' not in renderer

    def test_workspace_task_renderer_prefers_explicit_run_summary_before_file_change_rollup(self):
        """Run summaries should use explicit terminal summaries before falling back to file-change rollups."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function resolvedRunSummaryText(payload, card, fileChangeSummaries) {" in renderer
        assert "const explicitSummary = String(payload.summary || (card && card.dataset ? card.dataset.taskSummary || '' : '')).trim();" in renderer
        assert "if (explicitSummary && !/^任务已完成[。！!]?$/.test(explicitSummary)) return explicitSummary;" in renderer
        assert "if (fileChangeSummaries.length) return fileChangeSummaries.join('\\n');" in renderer
        assert "const summaryText = esc(resolvedRunSummaryText(payload, card, summaries));" in renderer

    def test_workspace_task_renderer_sets_multitarget_terminal_summary_once(self):
        """Multi-target runs should keep one canonical terminal summary instead of duplicating both raw and derived start/finish rows."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "if (kind === 'multi_target' && (rawType === 'multi_target.started' || rawType === 'multi_target.finished')) {" in renderer
        assert "function upsertMultiTargetTerminalRow(step, kind, html) {" in renderer
        assert "upsertMultiTargetTerminalRow(step, '', `<span class=\"wa-task-chip\">进行中</span>开始处理 ${total} 个目标文件`);" in renderer
        assert "upsertMultiTargetTerminalRow(step, 'done', `<span class=\"wa-task-chip ok\">完成</span>${esc(`全部 ${total} 个目标处理完成`)}`);" in renderer
        assert "function applyTerminalPayload(card, evt, payload, options) {" in renderer
        assert "summary.innerHTML = renderRunSummary(payload, card);" in renderer
        assert "if (cancelBtn) cancelBtn.remove();" in renderer
        assert "terminalStatus: multiTargetTerminalStatus(payload)," in renderer
        assert "statusText: multiTargetFinalStatusText(payload)," in renderer

    def test_workspace_task_renderer_restores_multitarget_terminal_status_after_refresh(self):
        """Multi-target terminal events should restore the final status text after queued file refreshes complete."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "async function finalizeTerminalRefresh(card, payload, options) {" in renderer
        assert "function multiTargetTerminalStatus(payload) {" in renderer
        assert "function multiTargetFinalStatusTextWithRefresh(payload, refreshOk) {" in renderer
        assert "setStatus(card, multiTargetFinalStatusTextWithRefresh(payload, refreshOk));" in renderer
        assert "await finalizeTerminalRefresh(card, payload, { multiTarget: true });" in renderer
        assert "} else if (evt.type === 'multi_target.finished') {" in renderer

    def test_workspace_task_renderer_flushes_refresh_recovery_through_one_helper(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "async function finalizeTerminalRefresh(card, payload, options) {" in renderer
        assert renderer.count("await finalizeTerminalRefresh(card, payload,") == 2
        assert renderer.count("const refreshOk = await flushQueuedFileRefreshes(card);") == 1
        assert "if (settings.showRefreshingStatus !== false) setStatus(card, '正在刷新文件');" in renderer

    def test_workspace_task_renderer_applies_terminal_payload_through_one_helper(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function applyTerminalPayload(card, evt, payload, options) {" in renderer
        assert "applyTerminalPayload(card, evt, payload, {" in renderer
        assert "terminalStatus: multiTargetTerminalStatus(payload)," in renderer
        assert "statusText: finalRunStatusText(payload)," in renderer

    def test_workspace_task_renderer_skips_duplicate_primary_step_finished_rows(self):
        """Primary phases should rely on step.result instead of rendering a second near-identical step.finished row."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "if (stepId === 'execute' || stepId === 'context' || stepId === 'check') return;" in renderer

    def test_workspace_task_renderer_avoids_duplicate_runtime_meta_in_awaiting_summary(self):
        """Awaiting-confirmation cards should not repeat runtime metadata in both the check step and the summary footer."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "const terminalStatus = String(card && card.dataset && card.dataset.taskTerminalStatus || '').trim().toLowerCase();" in renderer
        assert "const runtimeHtml = terminalStatus === 'awaiting_confirmation' ? '' : runtimeMetaHtml(payload);" in renderer

    def test_workspace_task_renderer_treats_repairable_check_failures_as_pending(self):
        """Repairable verification misses should not flash as hard failure while the task can still self-repair."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function isRepairableCheckStatus(status) {" in renderer
        assert "normalized === 'needs_attention'" in renderer
        assert "normalized === 'no_file_change'" in renderer
        assert "if (repairable && !ok) {" in renderer
        assert "const chipText = ok ? '通过' : (status === 'awaiting_confirmation' ? '待确认' : '需补齐');" in renderer

    def test_workspace_task_renderer_keeps_only_latest_repair_suggestion_row(self):
        """Repeated repair.proposed events should update one row instead of stacking noisy suggestions."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "upsertStepSingletonRow(step, 'repair.proposed:latest'" in renderer
        repair_start = renderer.find("if (type === 'repair.proposed') {")
        repair_end = renderer.find("if (type === 'step.result') {", repair_start)
        assert repair_start != -1 and repair_end != -1
        repair_block = renderer[repair_start:repair_end]
        assert "appendRow(step, 'warn repair'" not in repair_block

    def test_workspace_task_renderer_surfaces_intent_plan_hints(self):
        """Intent-plan metadata should add user-facing strategy and applyability hints without exposing raw internals."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "function intentStrategyLabel(value, outputMode) {" in renderer
        assert "if (normalized === 'analyze_then_confirm') return '先分析后确认';" in renderer
        assert "if (normalized === 'write_step_then_confirm') return '分步写入后确认';" in renderer
        assert "if (normalized === 'design_new_tool') return '需补工具';" in renderer
        assert "if (normalized === 'answer_only' && normalizedOutput === 'answer') return '';" in renderer
        assert "if (normalized === 'write_through' && normalizedOutput === 'write') return '';" in renderer
        assert "if (strategyLabel) chips.push(`策略：${strategyLabel}`);" in renderer
        assert "继续细化方案" in renderer
        assert "const previousTaskIntentStrategy = previewText(previousTaskTurn.task_intent_strategy || '', 120);" in dispatcher
        assert "context.previous_task_intent_strategy = previousTaskIntentStrategy;" in dispatcher
        assert "context.previous_task_intent_can_apply = previousTaskIntentCanApply;" in dispatcher
        assert "context.previous_task_intent_requires_confirmation = previousTaskIntentRequiresConfirmation;" in dispatcher

    def test_workspace_task_renderer_hides_placeholder_classification_metadata(self):
        """Default FileTask classification placeholders should stay internal unless they add user-facing meaning."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function shouldDisplayClassificationLabel(kind, value) {" in renderer
        assert "if (kind === 'request') return normalized !== 'new_task';" in renderer
        assert "if (kind === 'family') return normalized !== 'analyze';" in renderer
        assert "if (kind === 'operation') return normalized !== 'read';" in renderer
        assert "if (kind === 'execution') return normalized !== 'generic_tool_loop';" in renderer
        assert "if (operationLabel && operationLabel !== familyLabel) chips.push(`操作：${operationLabel}`);" not in renderer
        assert "if (targetFileType && chips.length) chips.push(`目标：${targetFileType.toUpperCase()}`);" in renderer
        assert "if (!classificationHtml && !reasonHtml) return '';" in renderer
        assert "chips.push(`置信：${Math.round(confidence * 100)}%`);" not in renderer

    def test_workspace_task_renderer_supports_plan_briefed_updates(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "if (type === 'plan.briefed') {" in renderer
        assert "setStatus(card, '已分析任务');" in renderer
        assert "const title = String(payload.title || '执行方案').trim() || '执行方案';" in renderer
        assert "payload.task_contract" not in renderer
        assert "const criteria = normalizedUserFacingItems(taskContract.acceptance_criteria);" not in renderer

    def test_workspace_task_renderer_formats_model_first_reason(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function classificationReasonLabel(reasonCode) {" in renderer
        assert "model_first" in renderer
        assert "先分析任务，再决定是否继续执行。" in renderer

    def test_workspace_task_renderer_filters_internal_plan_details(self):
        """Plan cards should keep model-facing completion criteria out of the visible UI."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function normalizeUserFacingPlanText(value) {" in renderer
        assert "按计划执行修改，并写回目标文件。" in renderer
        assert "const criteria = normalizedUserFacingItems(payload.success_criteria);" not in renderer
        assert "const criteria = normalizedUserFacingItems(taskContract.acceptance_criteria);" not in renderer
        assert "完成标准" not in renderer
        assert "可用工具家族" not in renderer

    def test_workspace_task_renderer_keeps_internal_specs_out_of_summary_rows(self):
        """Summary rows should keep next-step actions visible without exposing raw artifact specs or transport metadata."""
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function renderNextActionArtifact(artifact, followupRecord) {" in renderer
        assert "当前还缺少：${artifact.missing_capability}" in renderer
        assert "查看 Koto 下一步规格" not in renderer
        assert "AI 辅助判断" in renderer

    def test_workspace_task_renderer_treats_guard_events_as_internal_tools(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "const INTERNAL_TOOL_NAMES = new Set([" in renderer
        assert "'answer_guard'" in renderer
        assert "'repair_guard'" in renderer
        assert "'duplicate_guard'" in renderer

    def test_workspace_task_renderer_supports_simple_quick_action_mode(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "card.dataset.taskQuickActionMode = quickActionMode;" in renderer
        assert "data.quick_action_mode" in renderer
        assert "card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'simple'" in renderer
        assert "card.dataset.taskQuickActionMode || '').trim().toLowerCase() === 'proposal'" in renderer

    def test_workspace_model_selector_fetches_dynamic_catalog(self):
        """Workspace assistant should fetch the dynamic model catalog instead of relying on hardcoded options."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _refreshModelCatalog(force = false)" in src
        assert "fetch('/api/v1/models', { cache: 'no-store' })" in src
        assert "_syncModelStatusUi();" in src

    def test_workspace_model_state_syncs_from_server_status_on_init(self):
        """Workspace assistant should honor the persisted server-side local/cloud mode on startup."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _syncLockedModelFromServer()" in src
        assert "fetch('/api/local-model/status', { cache: 'no-store' })" in src
        assert "_syncLockedModelFromServer().finally(() => {" in src
        assert "_checkOllamaStatus();" in src

    def test_workspace_stream_handlers_consume_classification_events(self):
        """Workspace assistant streams should surface backend classification/model routing events."""
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        assert "applyRouteEvent: _applyRouteEvent," in assistant
        assert "if (parsed.type === 'classification' || parsed.type === 'route') {" in quick_actions
        assert "if (evt.type === 'classification' || evt.type === 'route') {" in quick_actions
        assert "options.applyRouteEvent(parsed);" in quick_actions
        assert "options.applyRouteEvent(evt);" in quick_actions

    def test_workspace_send_quick_action_routes_text_and_chart_via_unified_paths(self):
        """sendQuickAction should call editor/chart SSE helpers instead of legacy JSON quick-action."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        fn_start = src.find("window.WA.sendQuickAction = (action) => {")
        fn_end = src.find("window.WA.sendSelectionToAI = () => {", fn_start)
        assert fn_start != -1 and fn_end != -1
        send_quick = src[fn_start:fn_end]
        assert "_waTaskDispatcher.dispatchQuickAction(action, {" in send_quick
        assert "/api/v1/workspace/quick-action" not in send_quick

    def test_workspace_send_quick_action_clears_pending_task_followup_binding(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _clearPendingTaskResultFollowupBinding(noticeText) {" in src
        fn_start = src.find("window.WA.sendQuickAction = (action) => {")
        fn_end = src.find("window.WA.sendSelectionToAI = () => {", fn_start)
        assert fn_start != -1 and fn_end != -1
        send_quick = src[fn_start:fn_end]
        assert "_clearPendingTaskResultFollowupBinding();" in send_quick
        assert send_quick.find("_clearPendingTaskResultFollowupBinding();") < send_quick.find("_waTaskDispatcher.dispatchQuickAction(action, {")

    def test_workspace_selection_to_ai_reads_live_textarea_selection(self):
        """Plain-text editor selections should be read from the live textarea before pinning AI context."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _getActiveTextEditorSelectionForAI()" in src
        assert "textarea.selectionStart" in src
        assert "textarea.selectionEnd" in src

        send_selection_start = src.find("window.WA.sendSelectionToAI = () => {")
        send_selection_end = src.find("// Auto-expand the right AI panel if it's collapsed", send_selection_start)
        assert send_selection_start != -1 and send_selection_end != -1
        send_selection = src[send_selection_start:send_selection_end]
        assert "const liveSelection = _getLiveEditorSelectionForAI();" in send_selection

    def test_workspace_task_dispatcher_uses_current_open_file_as_context(self):
        """The input-box task route should carry the currently open file into FileTask payloads."""
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        assert "function wantsCurrentFile(text)" not in dispatcher
        assert "function currentFileContext(text)" not in dispatcher
        assert "function buildCurrentContextFile(" not in dispatcher
        assert "wantsCurrentFile," not in dispatcher
        assert "currentFileContext," not in dispatcher
        assert "function looksLikeCurrentFileMutation(text) {" in dispatcher
        assert "const currentFile = currentPath" in dispatcher
        assert "files.push(currentFile);" in dispatcher
        assert "if (!targetFile && currentFile && looksLikeCurrentFileMutation(text)) {" in dispatcher
        assert "current_file: currentFile ? {" in dispatcher
        assert "当前(?:打开的)?(?:\\s*[\\w.+#-]+)?\\s*(?:文件|文档)" not in dispatcher

    def test_workspace_quick_action_keyword_list_includes_check(self):
        """The workspace assistant quick-action keyword routing must recognize 检查."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        quick_start = src.find("window.WA.quickAction = (text) => {")
        quick_end = src.find("window.WA.pptxSync = (ta) => {", quick_start)
        assert quick_start != -1 and quick_end != -1
        quick_section = src[quick_start:quick_end]
        assert "_waTaskDispatcher.matchQuickAction(text)" in quick_section
        assert "attachedDispatcher.registerQuickActionKeyword(keyword, action.action);" in quick_actions
        assert "action: '检查'" in quick_actions
        assert "keywords: ['检查']" in quick_actions
        assert "WA.sendQuickAction(matchedAction);" in quick_section

    def test_pdf_ai_annotate_is_explicitly_disabled_during_migration(self):
        """PDF AI annotate should not call the legacy quick-action path while the feature is offline."""
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        fn_start = src.find("async aiAnnotate() {")
        fn_end = src.find("// ─── AI Watermark removal", fn_start)
        assert fn_start != -1 and fn_end != -1
        ai_annotate = src[fn_start:fn_end]
        assert "/api/v1/workspace/quick-action" not in ai_annotate
        assert "ai_annotate" not in ai_annotate
        assert "AI 标注功能正在迁移到新的 AI 流程" in ai_annotate

    def test_pdf_ai_annotate_button_title_marks_temporary_unavailability(self):
        """The PDF toolbar button should advertise that AI annotate is temporarily unavailable."""
        html = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        assert 'title="AI 标注迁移中，暂不可用"' in html

    def test_workspace_templates_use_shared_model_controls_partial(self):
        """Workspace templates should share the same local/cloud model controls without exposing a redundant model picker."""
        standalone_html = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
        partial_html = Path("web/templates/_workspace_model_controls.html").read_text(encoding="utf-8")
        assert "{% include '_workspace_model_controls.html' %}" in standalone_html
        assert "{% include '_workspace_model_controls.html' %}" in index_html
        assert 'id="wa-model-mode-toggle"' in partial_html
        assert 'id="wa-model-mode-cloud-btn"' in partial_html
        assert 'id="wa-model-mode-local-btn"' in partial_html
        assert 'id="wa-model-select"' not in partial_html
        assert 'id="wa-model-mode-cloud-btn"' not in standalone_html
        assert 'id="wa-model-mode-local-btn"' not in standalone_html
        assert 'id="wa-model-mode-cloud-btn"' not in index_html
        assert 'id="wa-model-mode-local-btn"' not in index_html

    def test_workspace_cloud_selection_maps_request_model_mode_to_cloud(self):
        js = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        partial_html = Path("web/templates/_workspace_model_controls.html").read_text(encoding="utf-8")
        assert "lockedModel: localStorage.getItem('wa_locked_model') === 'local' ? 'local' : 'cloud'" in js
        assert "const storedLockedModel = localStorage.getItem('wa_locked_model');" in js
        assert "return state.lockedModel === 'local' ? 'local' : 'cloud';" in js
        assert "typeof options.getModelMode === 'function' ? options.getModelMode() : 'cloud'" in quick_actions
        assert "typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto'" not in quick_actions
        assert "model_mode: payload.model_mode || getModelMode()," in quick_actions
        assert "model_mode: modelMode," in quick_actions
        assert "const normalized = String(val || '').trim().toLowerCase() === 'local' ? 'local' : 'cloud';" in js
        assert "auto" not in partial_html.lower()
        assert ">云端<" in partial_html

    def test_mobile_ai_model_settings_do_not_offer_auto_model_choice(self):
        mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
        assert '<option value="auto">🤖 Auto</option>' not in mobile_html
        assert "const model = ai.default_model || 'gemini-3-flash-preview';" in mobile_html

    def test_workspace_task_renderer_supports_conversion_cancel_and_robust_sse(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        assert "list_conversions: '查询可转换格式'" in renderer
        assert "convert_file: '格式转换'" in renderer
        assert "'convert_file'," in renderer
        assert "payload.operation === 'convert_file'" in renderer
        assert "window.WA.cancelFileTaskRun = async function cancelFileTaskRun(runId)" in renderer
        assert "cancel" + "White" + "box" + "TaskRun" not in renderer
        assert "function parseSseEvents(buffer, flush)" in renderer

    def test_workspace_markdown_renderers_sanitize_model_html(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        assert "function _sanitizeRenderedHtml(html)" in assistant
        assert "_sanitizeRenderedHtml(window.marked.parse" in assistant
        assert "function sanitizeRenderedHtml(html)" in quick_actions
        assert "sanitizeRenderedHtml(window.marked.parse" in quick_actions

    def test_workspace_quick_actions_do_not_render_raw_tool_result_previews_as_progress(self):
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        assert "function toolResultProgressText(parsed) {" in quick_actions
        assert "setProgress(toolResultProgressText(parsed));" in quick_actions
        assert "setProgress(parsed.result_preview" not in quick_actions


class TestMainChatProgressRegression:
    """Regression checks for canonical step-event support in the main chat UI."""

    def test_main_chat_normalizes_canonical_step_events(self):
        src = Path("web/static/js/app.js").read_text(encoding="utf-8")
        assert "evt.type === 'plan'" in src
        assert "evt.type === 'phase'" in src
        assert "evt.type === 'step_start'" in src
        assert "evt.type === 'tool_call'" in src
        assert "const canonicalProgressPercent =" in src


class TestRemovedLegacyTaskRoutes:
    """Regression checks that old file-task compatibility routes are gone."""

    def test_skill_execute_route_is_not_registered(self, app_client):
        resp = app_client.post("/api/editor/ai/skill-execute", json={})
        assert resp.status_code == 404

    def test_task_execute_route_is_not_registered(self, app_client):
        resp = app_client.post("/api/editor/ai/task-execute", json={"task": "整理当前文件"})
        assert resp.status_code == 404


class TestLegacyDocumentCompatRoutes:
    """Legacy document APIs should reuse the current DocumentFeedbackSystem paths instead of old batch annotators."""

    def test_web_app_doc_annotate_paths_use_compat_helper(self):
        src = Path("web/app.py").read_text(encoding="utf-8")

        assert "from web.document_annotation_compat import (" in src
        assert "iter_annotation_progress_events(" in src
        assert "collect_annotation_result(" in src
        assert "DocumentFeedbackSystem" not in src

    @staticmethod
    def _make_document_client(monkeypatch, workspace_root):
        from flask import Flask
        import web.blueprints.document as document_routes

        app = Flask(__name__)
        app.config["TESTING"] = True
        monkeypatch.setattr(document_routes, "_get_client", lambda: object())
        monkeypatch.setattr(document_routes, "_get_workspace_dir", lambda: str(workspace_root))
        app.register_blueprint(document_routes.document_bp)
        return app.test_client()

    def test_document_annotate_route_uses_streaming_compat_path(self, monkeypatch, tmp_path):
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "legacy-annotate.docx"
        docx_path.write_bytes(b"PK\x03\x04")
        revised_path = tmp_path / "legacy-annotate_revised.docx"
        client = self._make_document_client(monkeypatch, tmp_path)

        class FakeFeedback:
            def __init__(self, gemini_client=None, default_model_id="gemini-2.5-pro"):
                self.gemini_client = gemini_client
                self.default_model_id = default_model_id

            def full_annotation_loop(self, *args, **kwargs):
                raise AssertionError("legacy sync annotation loop should not be used")

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(revised_path),
                        "applied": 3,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        resp = client.post(
            "/api/document/annotate",
            json={
                "file_path": str(docx_path),
                "requirement": "请标注翻译问题",
            },
        )

        body = resp.get_json()
        assert resp.status_code == 200
        assert body["success"] is True
        assert body["revised_file"] == str(revised_path)
        assert body["applied"] == 3

    def test_document_analyze_annotations_route_uses_chunked_feedback_path(self, monkeypatch, tmp_path):
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "legacy-analyze.docx"
        docx_path.write_bytes(b"PK\x03\x04")
        client = self._make_document_client(monkeypatch, tmp_path)

        class FakeFeedback:
            def __init__(self, gemini_client=None, default_model_id="gemini-2.5-pro"):
                self.gemini_client = gemini_client
                self.default_model_id = default_model_id

            def analyze_for_annotation_chunked(self, *args, **kwargs):
                return {
                    "success": True,
                    "annotations": [{"原文片段": "foo", "修改建议": "bar"}],
                    "annotation_count": 1,
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        resp = client.post(
            "/api/document/analyze-annotations",
            json={
                "file_path": str(docx_path),
                "requirement": "请只分析并标出问题",
            },
        )

        body = resp.get_json()
        assert resp.status_code == 200
        assert body["success"] is True
        assert body["annotation_count"] == 1
        assert body["annotations"][0]["原文片段"] == "foo"

    def test_document_batch_annotate_stream_route_uses_feedback_streaming_path(self, monkeypatch, tmp_path):
        import web.document_feedback as feedback_module

        docx_path = tmp_path / "legacy-batch.docx"
        docx_path.write_bytes(b"PK\x03\x04")
        revised_path = tmp_path / "legacy-batch_revised.docx"
        client = self._make_document_client(monkeypatch, tmp_path)

        class FakeFeedback:
            def __init__(self, gemini_client=None, default_model_id="gemini-2.5-pro"):
                self.gemini_client = gemini_client
                self.default_model_id = default_model_id

            def full_annotation_loop_streaming(self, *args, **kwargs):
                yield {
                    "stage": "reading",
                    "progress": 5,
                    "message": "读取中",
                    "detail": "第 1 批",
                }
                yield {
                    "stage": "complete",
                    "result": {
                        "success": True,
                        "revised_file": str(revised_path),
                        "applied": 2,
                    },
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        resp = client.post(
            "/api/document/batch-annotate-stream",
            json={
                "file_path": str(docx_path),
                "requirement": "请流式标注",
            },
        )

        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "event: progress" in body
        assert "event: complete" in body
        assert revised_path.name in body

    def test_document_feedback_route_resolves_relative_path_before_wrapper(self, monkeypatch, tmp_path):
        import web.document_feedback as feedback_module

        documents_dir = tmp_path / "documents"
        documents_dir.mkdir()
        docx_path = documents_dir / "legacy-feedback.docx"
        docx_path.write_bytes(b"PK\x03\x04")
        client = self._make_document_client(monkeypatch, tmp_path)
        captured = {}

        class FakeFeedback:
            def __init__(self, gemini_client=None, default_model_id="gemini-2.5-pro"):
                self.gemini_client = gemini_client
                self.default_model_id = default_model_id

            def full_feedback_loop(self, file_path, user_requirement="", auto_apply=True):
                captured["file_path"] = file_path
                captured["user_requirement"] = user_requirement
                captured["auto_apply"] = auto_apply
                return {
                    "success": True,
                    "new_file_path": str(docx_path.with_name("legacy-feedback_revised.docx")),
                    "applied_count": 1,
                }

        monkeypatch.setattr(feedback_module, "DocumentFeedbackSystem", FakeFeedback)

        resp = client.post(
            "/api/document/feedback",
            json={
                "file_path": "legacy-feedback.docx",
                "requirement": "请润色措辞",
                "auto_apply": False,
            },
        )

        body = resp.get_json()
        assert resp.status_code == 200
        assert body["success"] is True
        assert captured == {
            "file_path": str(docx_path),
            "user_requirement": "请润色措辞",
            "auto_apply": False,
        }

class TestLegacyEditorRemovalRegression:
    """Regression checks for removing the old Univer editor stack."""

    def test_legacy_univer_entrypoints_are_removed(self):
        assert not Path("web/univer-editor/index.html").exists()
        assert not Path("web/static/univer-dist/index.html").exists()

    def test_legacy_univer_source_tree_is_removed(self):
        assert not Path("web/univer-editor/main.js").exists()
        assert not Path("web/univer-editor/src").exists()

    def test_workspace_assistant_still_loads_sheets_runtime(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "/static/univer-dist/assets/sheets-main.css" in src
        assert "/static/univer-dist/assets/sheets-main.js" in src
        assert Path("web/static/univer-dist/assets/sheets-main.css").exists()
        assert Path("web/static/univer-dist/assets/sheets-main.js").exists()

    def test_univer_editor_build_only_targets_sheets_runtime(self):
        pkg = Path("web/univer-editor/package.json").read_text(encoding="utf-8")
        assert '"build": "npm run build:sheets && npm run clean:assets"' in pkg
        assert '"build:editor"' not in pkg


class TestTaskAgentDocumentEdits:
    """Regression checks for real file-edit tool execution in TaskAgent."""

    def test_task_agent_local_prompt_prefers_real_excel_to_word_table(self):
        prompt = (ROOT / "app/core/agent/task_agent.py").read_text(encoding="utf-8")

        assert "insert_excel_as_docx_table" in prompt
        assert "insert_image_into_docx" in prompt
        assert "先用 `write_docx_content` 把基于真实表格数据生成的摘要/结论写入目标文档" in prompt
        assert "write_docx_content" in prompt

    def test_task_agent_runs_stage_verification_after_file_change(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [
                    {"name": "insert_excel_as_docx_table"},
                    {"name": "verify_task_completion"},
                ]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                if tool_name == "insert_excel_as_docx_table":
                    return json.dumps({
                        "success": True,
                        "summary": "已将工作表“汇总表”的 200 行数据写入 Word 表格",
                        "path": "target.docx",
                        "file_type": "docx",
                        "change_type": "modify",
                        "operation": tool_name,
                        "preview": "表格已写入目标文档",
                    }, ensure_ascii=False)
                if tool_name == "verify_task_completion":
                    payload = json.loads(tool_args["file_states"])
                    assert payload and payload[0]["path"] == "target.docx"
                    return json.dumps({
                        "completed": True,
                        "confidence": 0.96,
                        "summary": "结果符合要求，目标文档已经完成更新",
                        "remaining_steps": [],
                    }, ensure_ascii=False)
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        registry = FakeRegistry()
        llm_call_count = {"count": 0}

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            llm_call_count["count"] += 1
            return {
                "content": "先执行插表，再检查结果。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": "sales.xlsx",
                        "target_path": "target.docx",
                        "sheet_name": "汇总表",
                    },
                }],
            }

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="将 xls 表格加入 docx，并确认结果符合要求",
            files=[],
            options={"model_mode": "local"},
        ))

        assert llm_call_count["count"] == 1
        assert [name for name, _ in registry.executions] == [
            "insert_excel_as_docx_table",
            "verify_task_completion",
        ]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "step_progress" and "检查当前结果是否符合任务要求" in str(e.get("detail", ""))
            for e in events
        )
        assert any(
            e.get("type") == "step_done" and "结果符合要求" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "done" and "结果符合要求" in str(e.get("summary", ""))
            for e in events
        )

    def test_task_agent_executes_textual_task_tool_call_fallback(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [
                    {"name": "insert_excel_as_docx_table"},
                    {"name": "verify_task_completion"},
                ]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                if tool_name == "insert_excel_as_docx_table":
                    return json.dumps({
                        "success": True,
                        "summary": "已将工作表“销售台账”的 24 行数据写入 Word 表格",
                        "path": "target.docx",
                        "file_type": "docx",
                        "change_type": "modify",
                        "operation": tool_name,
                        "preview": "客户 | 地区 | 金额",
                    }, ensure_ascii=False)
                if tool_name == "verify_task_completion":
                    return json.dumps({
                        "completed": True,
                        "confidence": 0.93,
                        "summary": "目标文档已追加销售台账表格",
                        "remaining_steps": [],
                    }, ensure_ascii=False)
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        registry = FakeRegistry()
        llm_call_count = {"count": 0}

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            llm_call_count["count"] += 1
            return {
                "content": (
                    "为了将《销售台账.xlsx》中的信息加入到《雷鸟访谈问题.docx》中，我将直接把销售台账的数据作为 Word 表格追加到文档末尾。\n\n"
                    "下面开始执行插入操作。\n\n"
                    "```json\n"
                    "{\"name\": \"insert_excel_as_docx_table\", \"arguments\": {\"source_path\": \"sales.xlsx\", \"target_path\": \"target.docx\", \"table_title\": \"附录：销售台账数据\"}}\n"
                    "```"
                ),
                "tool_calls": [],
            }

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="将 xlsx 信息加入 docx，并确认已经写入目标文件",
            files=[],
            options={"model_mode": "cloud"},
        ))

        assert llm_call_count["count"] == 1
        assert [name for name, _ in registry.executions] == [
            "insert_excel_as_docx_table",
            "verify_task_completion",
        ]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "tool_call" and e.get("tool_name") == "insert_excel_as_docx_table"
            for e in events
        )
        assert any(
            e.get("type") == "done" and "目标文档已追加销售台账表格" in str(e.get("summary", ""))
            for e in events
        )
        assert not any(
            e.get("type") == "result" and "insert_excel_as_docx_table" in str(e.get("data", ""))
            for e in events
        )

    def test_task_agent_reinjects_stage_verification_feedback_when_incomplete(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def get_definitions(self):
                return [
                    {"name": "write_docx_content"},
                    {"name": "verify_task_completion"},
                ]

            def execute(self, tool_name, tool_args):
                if tool_name == "write_docx_content":
                    return json.dumps({
                        "success": True,
                        "summary": "已写入 2 个段落到 Word 文档",
                        "path": "draft.docx",
                        "file_type": "docx",
                        "change_type": "modify",
                        "operation": tool_name,
                        "preview": "第一段\n第二段",
                    }, ensure_ascii=False)
                if tool_name == "verify_task_completion":
                    return json.dumps({
                        "completed": False,
                        "confidence": 0.41,
                        "summary": "当前文档还缺少结论段",
                        "remaining_steps": ["补充结论段"],
                    }, ensure_ascii=False)
                raise AssertionError(f"Unexpected tool call: {tool_name}")

        seen_message_batches = []
        responses = iter([
            {
                "content": "先写入主体内容。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "write_docx_content",
                    "args": {"path": "draft.docx", "paragraphs": []},
                }],
            },
            {
                "content": "继续补充结论段。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: FakeRegistry())

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            seen_message_batches.append(messages)
            return next(responses)

        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        _ = "".join(agent.execute(task="补全文档并保证结构完整", files=[], options={}))

        assert len(seen_message_batches) == 2
        verify_messages = [m for m in seen_message_batches[1] if m.get("name") == "verify_task_completion"]
        assert verify_messages
        assert "缺少结论段" in verify_messages[-1]["content"]

    def test_task_agent_skips_duplicate_tool_calls_within_single_batch(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [{"name": "insert_excel_as_docx_table"}]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                return json.dumps({
                    "success": True,
                    "summary": "已将工作表“汇总表”的 200 行数据写入 Word 表格",
                    "path": "target.docx",
                    "file_type": "docx",
                    "change_type": "modify",
                    "operation": tool_name,
                }, ensure_ascii=False)

        registry = FakeRegistry()
        duplicate_args = {
            "source_path": "sales.xlsx",
            "target_path": "target.docx",
            "sheet_name": "汇总表",
            "table_title": "汇总表",
        }
        responses = iter([
            {
                "content": "先把 Excel 插入 Word 表格。",
                "tool_calls": [
                    {"id": "call_1", "name": "insert_excel_as_docx_table", "args": duplicate_args},
                    {"id": "call_2", "name": "insert_excel_as_docx_table", "args": dict(duplicate_args)},
                ],
            },
            {
                "content": "目标文档已经更新完成。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(task="将 xls 表格插入 docx", files=[], options={}))

        assert registry.executions == [("insert_excel_as_docx_table", duplicate_args)]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "thought" and "重复工具调用" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "tool_result" and "已跳过重复工具调用" in str(e.get("result_preview", ""))
            for e in events
        )

    def test_task_agent_stops_before_repeating_identical_successful_tool_batch(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [{"name": "parse_file_to_text"}]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                return "第一轮读取成功"

        registry = FakeRegistry()
        repeated_call = {
            "id": "call_1",
            "name": "parse_file_to_text",
            "args": {"path": "demo.txt", "max_chars": 12000},
        }
        responses = iter([
            {
                "content": "先读取当前文件。",
                "tool_calls": [repeated_call],
            },
            {
                "content": "继续读取当前文件。",
                "tool_calls": [{
                    "id": "call_2",
                    "name": "parse_file_to_text",
                    "args": {"path": "demo.txt", "max_chars": 12000},
                }],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(task="总结当前文件", files=[], options={}))

        assert registry.executions == [("parse_file_to_text", {"path": "demo.txt", "max_chars": 12000})]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "thought" and "重复请求同一组工具" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "done" and "检测到重复步骤" in str(e.get("summary", ""))
            for e in events
        )

    def test_task_agent_reinjects_failed_tool_feedback_for_sandbox_style_errors(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [{"name": "run_python_code"}]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                return "[error] 执行失败：unsupported operand type(s) for +: 'float' and 'str'"

        registry = FakeRegistry()
        seen_message_batches = []
        responses = iter([
            {
                "content": "先执行 Python 代码。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {"code": "print(1)"},
                }],
            },
            {
                "content": "我已经知道上一轮失败了。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            seen_message_batches.append(messages)
            return next(responses)

        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(task="把 xlsx 信息加入 docx", files=[], options={"model_mode": "local"}))

        events = parse_sse_events(payload.encode("utf-8"))
        assert registry.executions == [("run_python_code", {"code": "print(1)"})]
        assert any(
            e.get("type") == "step_error" and "unsupported operand type" in str(e.get("error", ""))
            for e in events
        )
        assert not any(
            e.get("type") == "step_done" and e.get("step_id") == "run_python_code_1_1"
            for e in events
        )

        assert len(seen_message_batches) == 2
        corrective_prompts = [
            msg.get("content", "")
            for msg in seen_message_batches[1]
            if msg.get("role") == "user" and "上一轮工具调用失败" in str(msg.get("content", ""))
        ]
        assert corrective_prompts
        assert "unsupported operand type" in corrective_prompts[-1]
        assert "不要重复完全相同的工具调用、参数或代码" in corrective_prompts[-1]

    def test_task_agent_stops_before_repeating_identical_failed_tool_batch(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def __init__(self):
                self.executions = []

            def get_definitions(self):
                return [{"name": "run_python_code"}]

            def execute(self, tool_name, tool_args):
                self.executions.append((tool_name, dict(tool_args)))
                return "[error] 执行失败：unsupported operand type(s) for +: 'float' and 'str'"

        registry = FakeRegistry()
        repeated_call = {
            "id": "call_1",
            "name": "run_python_code",
            "args": {"code": "print(1)"},
        }
        responses = iter([
            {
                "content": "先执行 Python 代码。",
                "tool_calls": [repeated_call],
            },
            {
                "content": "再试一次相同代码。",
                "tool_calls": [{
                    "id": "call_2",
                    "name": "run_python_code",
                    "args": {"code": "print(1)"},
                }],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: registry)
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(task="把 xlsx 信息加入 docx", files=[], options={"model_mode": "local"}))

        assert registry.executions == [("run_python_code", {"code": "print(1)"})]
        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "thought" and "重复提交上一轮失败的工具调用" in str(e.get("text", ""))
            for e in events
        )
        assert any(
            e.get("type") == "done" and "检测到重复失败步骤" in str(e.get("summary", ""))
            for e in events
        )

    def test_resolve_requested_model_id_falls_back_when_unavailable(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {}

            def get_available_models(self):
                return [{"id": "gemini-2.5-flash"}]

            def get_model_for_task(self, task):
                return "gemini-2.5-flash"

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())

        assert (
            webapp._resolve_requested_model_id(
                "gemini-2.5-pro",
                fallback_model="gemini-3.1-pro-preview",
            )
            == "gemini-2.5-flash"
        )

    def test_resolve_requested_model_id_rejects_image_model_for_chat(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {
                "gemini-3.1-flash-image-preview": {
                    "image_gen": True,
                    "multimodal": True,
                    "grounding": False,
                    "function_calling": False,
                    "tier": 7,
                }
            }

            def get_available_models(self):
                return [
                    {"id": "gemini-3.1-flash-image-preview"},
                    {"id": "gemini-2.5-flash"},
                ]

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())

        assert (
            webapp._resolve_requested_model_id(
                "gemini-3.1-flash-image-preview",
                fallback_model="gemini-2.5-flash",
                task_type="CHAT",
            )
            == "gemini-2.5-flash"
        )

    def test_resolve_requested_model_id_rejects_model_without_required_task_capability(self, monkeypatch):
        import web.app as webapp

        class _DummyManager:
            _cached_caps = {
                "gemini-2.5-flash": {
                    "speed": 10,
                    "quality": 8,
                    "reasoning": 8,
                    "context": 8,
                    "multimodal": True,
                    "grounding": False,
                    "function_calling": True,
                    "image_gen": False,
                    "tier": 8,
                }
            }

            def get_available_models(self):
                return [
                    {"id": "gemini-2.5-flash"},
                    {"id": "gemini-2.5-pro"},
                ]

        monkeypatch.setattr(webapp, "_model_manager", _DummyManager())

        assert (
            webapp._resolve_requested_model_id(
                "gemini-2.5-flash",
                fallback_model="gemini-2.5-pro",
                task_type="WEB_SEARCH",
            )
            == "gemini-2.5-pro"
        )

    def test_parse_file_to_text_accepts_larger_custom_windows(self, tmp_path):
        from app.core.agent.task_tools import parse_file_to_text

        source_path = tmp_path / "long_notes.txt"
        source_path.write_text("A" * 20_000, encoding="utf-8")

        parsed = parse_file_to_text(str(source_path), max_chars=18_000)

        assert len(parsed) == 18_000
        assert len(parsed) > 12_000

    def test_task_agent_keeps_long_tool_results_in_followup_context(self, monkeypatch):
        from app.core.agent.task_agent import TaskAgent

        class FakeRegistry:
            def get_definitions(self):
                return [{"name": "parse_file_to_text"}]

            def execute(self, tool_name, tool_args):
                return "B" * 12_000

        seen_message_batches = []
        responses = iter([
            {
                "content": "先读取文件全文。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "parse_file_to_text",
                    "args": {"path": "demo.txt", "max_chars": 12000},
                }],
            },
            {
                "content": "已完成。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(TaskAgent, "_build_registry", lambda self, files=None: FakeRegistry())

        def fake_call_llm(self, provider, messages, system, tool_defs, options=None):
            seen_message_batches.append(messages)
            return next(responses)

        monkeypatch.setattr(TaskAgent, "_call_llm", fake_call_llm)

        agent = TaskAgent(model_id="test-model")
        _ = "".join(agent.execute(task="读取大文件", files=[], options={}))

        assert len(seen_message_batches) == 2
        function_messages = [m for m in seen_message_batches[1] if m.get("role") == "function"]
        assert function_messages
        assert len(function_messages[-1]["content"]) > 4000

    def test_task_agent_run_python_code_can_open_attached_file_by_basename(self, tmp_path, monkeypatch):
        openpyxl = pytest.importorskip("openpyxl")

        source_path = tmp_path / "销售台账.xlsx"

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "销售数据"
        worksheet.append(["姓名", "地区", "销售额"])
        worksheet.append(["张三", "华东", 120])
        workbook.save(source_path)
        workbook.close()

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "先用 Python 读取附件中的 Excel。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {
                        "code": (
                            "import openpyxl\n"
                            "wb = openpyxl.load_workbook('销售台账.xlsx', read_only=True, data_only=True)\n"
                            "ws = wb.active\n"
                            "print(ws['A2'].value)\n"
                            "wb.close()\n"
                        )
                    },
                }],
            },
            {
                "content": "已成功读取附件文件。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="读取附件里的 Excel 并打印第一行数据",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "xlsx"},
            ],
            options={},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert any(
            e.get("type") == "tool_result" and "张三" in str(e.get("result_preview", ""))
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    def test_run_python_in_sandbox_syncs_modified_attached_file_when_cleanup_fails(self, tmp_path, monkeypatch):
        from app.core.agent import task_tools

        source_path = tmp_path / "任务说明.txt"
        source_path.write_text("before", encoding="utf-8")

        cleanup_calls = {"count": 0}
        original_rmtree = task_tools.shutil.rmtree

        def flaky_rmtree(path, *args, **kwargs):
            cleanup_calls["count"] += 1
            if cleanup_calls["count"] == 1:
                raise PermissionError(32, "locked", path)
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(task_tools.shutil, "rmtree", flaky_rmtree)

        result = task_tools.run_python_in_sandbox(
            (
                "from pathlib import Path\n"
                f"p = Path(TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
                "p.write_text('after', encoding='utf-8')\n"
                f"print('KOTO_MODIFIED:' + TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
            ),
            timeout=10,
            task_files=[{"path": str(source_path), "name": source_path.name}],
        )

        assert "Sandbox error:" not in result
        assert "__koto_modified__" in result
        assert str(source_path) in result
        assert source_path.read_text(encoding="utf-8") == "after"
        assert cleanup_calls["count"] == 2

    def test_run_python_in_sandbox_accepts_string_timeout(self):
        from app.core.agent import task_tools

        result = task_tools.run_python_in_sandbox("print('ok')", timeout="30")

        assert "unsupported operand type" not in result
        assert result.get("error") == ""
        assert result.get("stdout", "").strip() == "ok"

    def test_task_agent_run_python_code_syncs_modified_attached_file_and_emits_file_change(self, tmp_path, monkeypatch):
        source_path = tmp_path / "任务说明.txt"
        source_path.write_text("before", encoding="utf-8")

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "先用 Python 修改附件内容。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {
                        "code": (
                            "from pathlib import Path\n"
                            f"p = Path(TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
                            "p.write_text('after', encoding='utf-8')\n"
                            f"print('KOTO_MODIFIED:' + TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
                        )
                    },
                }],
            },
            {
                "content": "已完成附件修改。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="把附件内容改成 after",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "txt"},
            ],
            options={"model_mode": "local"},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert source_path.read_text(encoding="utf-8") == "after"
        assert any(
            e.get("type") == "file_change"
            and e.get("path") == str(source_path)
            and e.get("change_type") == "modify"
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    def test_task_agent_run_python_code_detects_direct_source_file_modification(self, tmp_path, monkeypatch):
        source_path = tmp_path / "任务说明.txt"
        source_path.write_text("before", encoding="utf-8")

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "直接修改原始附件路径。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "run_python_code",
                    "args": {
                        "code": (
                            "from pathlib import Path\n"
                            f"p = Path(TASK_FILE_PATHS[{source_path.name!r}])\n"
                            "p.write_text('after-direct', encoding='utf-8')\n"
                            "print('done')\n"
                        )
                    },
                }],
            },
            {
                "content": "已完成原文件修改。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="把原始附件内容改成 after-direct",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "txt"},
            ],
            options={"model_mode": "local"},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert source_path.read_text(encoding="utf-8") == "after-direct"
        assert any(
            e.get("type") == "file_change"
            and e.get("path") == str(source_path)
            and e.get("change_type") == "modify"
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

    def test_task_agent_inserts_excel_table_into_docx_and_emits_file_change(self, tmp_path, monkeypatch):
        openpyxl = pytest.importorskip("openpyxl")
        docx_module = pytest.importorskip("docx")

        source_path = tmp_path / "销售台账.xlsx"
        target_path = tmp_path / "雷鸟访问问题.docx"

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "销售数据"
        worksheet.append(["姓名", "地区", "销售额"])
        worksheet.append(["张三", "华东", 120])
        worksheet.append(["李四", "华南", 98])
        workbook.save(source_path)
        workbook.close()

        document = docx_module.Document()
        document.add_paragraph("雷鸟访问问题说明")
        document.save(target_path)

        from app.core.agent.task_agent import TaskAgent

        responses = iter([
            {
                "content": "先读取 Excel，并把数据写成 Word 表格。",
                "tool_calls": [{
                    "id": "call_1",
                    "name": "insert_excel_as_docx_table",
                    "args": {
                        "source_path": str(source_path),
                        "target_path": str(target_path),
                        "sheet_name": "销售数据",
                        "table_title": "销售台账",
                    },
                }],
            },
            {
                "content": "已完成 Excel 到 Word 表格写入，并校验目标文档。",
                "tool_calls": [],
            },
        ])

        monkeypatch.setattr(TaskAgent, "_get_provider", lambda self, options=None: object())
        monkeypatch.setattr(
            TaskAgent,
            "_call_llm",
            lambda self, provider, messages, system, tool_defs, options=None: next(responses),
        )

        agent = TaskAgent(model_id="test-model")
        payload = "".join(agent.execute(
            task="将excel数据加入word，做一个新表格",
            files=[
                {"path": str(source_path), "name": source_path.name, "type": "xlsx"},
                {"path": str(target_path), "name": target_path.name, "type": "docx"},
            ],
            options={},
        ))

        events = parse_sse_events(payload.encode("utf-8"))
        assert any(e.get("type") == "file_change" for e in events)
        assert any(
            e.get("type") == "file_change" and str(e.get("path", "")).endswith("雷鸟访问问题.docx")
            for e in events
        )
        assert any(e.get("type") == "done" for e in events)

        updated_doc = docx_module.Document(target_path)
        assert updated_doc.tables
        first_table = updated_doc.tables[0]
        assert first_table.cell(0, 0).text == "姓名"
        assert first_table.cell(1, 0).text == "张三"
        assert first_table.cell(2, 1).text == "华南"


class TestWorkspaceAssistantTaskRemovalRegression:
    """Source-level regressions for removing file-assistant AI task/chat flows."""

    def test_workspace_assistant_removes_old_task_stream_senders(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "async function _waSendToOpenClawTask" not in src
        assert "function _waBuildOpenClawTaskMessage" not in src
        assert "async function _waSendToAgent" not in src
        assert "async function _waSendToChat" not in src
        assert "async function _waSendToInline" not in src
        assert "window.WA.applyAIResponse = (mode, btn) =>" not in src
        assert "window.WA.setOutputMode = () =>" not in src
        assert "function _refreshWorkflowChips() {}" not in src
        assert "async function _appendWorkflowChips() {}" not in src
        assert "async function _suggestWorkflows() {}" not in src
        assert "fetch('/api/chat/stream'" not in src
        assert "fetch('/api/agent/chat'" not in src
        assert "action: 'ai_task'" not in src

    def test_workspace_send_message_keeps_open_file_and_uses_file_task_stream(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        send_start = src.index("window.WA.sendMessage = () => {")
        send_end = src.index("// ── Auto-save", send_start)
        send_block = src[send_start:send_end]
        assert "appendUserMessageWithLoading" in send_block
        assert "_waTaskDispatcher.dispatchMessage({" in send_block
        assert "/api/editor/ai/task-stream" not in send_block
        assert "_waSendToOpenClawTask(" not in send_block
        assert "_waSendToAgent(" not in send_block
        assert "_waSendToChat(" not in send_block

    def test_workspace_send_message_builds_file_task_payload_with_target_path_history_and_model_state(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        send_start = assistant.index("window.WA.sendMessage = () => {")
        send_end = assistant.index("// ── Auto-save", send_start)
        send_block = assistant[send_start:send_end]

        assert "pinnedSelText," in send_block
        assert "pinnedSelSource," in send_block
        assert "_waTaskDispatcher.dispatchMessage({" in send_block
        assert "function buildFileTaskPayload(text, pinnedSelText, pinnedSelSource, overrides) {" in dispatcher
        assert "function buildTaskContextPackage(params) {" in dispatcher
        assert "context_version: 'koto_task_context_v1'" in dispatcher
        assert "const currentPath = typeof options.getCurrentAIContextPath === 'function'" in dispatcher
        assert "const currentPathKey = normalizeTaskPath(currentPath);" in dispatcher
        assert "const currentFile = currentPath" in dispatcher
        assert "files.push(currentFile);" in dispatcher
        assert "function inferAttachedWriteTargetFile(text, files) {" in dispatcher
        assert "function hasReadOnlyHint(text) {" in dispatcher
        assert "if (hasReadOnlyHint(lowered)) return false;" in dispatcher
        assert "const currentContextAttachment = (!targetFile && currentPathKey)" not in dispatcher
        assert "const inferredAttachedTargetFile = !targetFile ? inferAttachedWriteTargetFile(text, files) : null;" in dispatcher
        assert "if (!targetFile && inferredAttachedTargetFile) {" in dispatcher
        assert "if (!targetFile && currentFile && looksLikeCurrentFileMutation(text)) {" in dispatcher
        assert "const hasExplicitFiles = files.length > 0;" not in dispatcher
        assert "const shouldUseCurrentContextAsTarget = !!currentPath && !targetFile;" not in dispatcher
        assert "const inferredTargetPath = targetFile" in dispatcher
        assert "target_path: inferredTargetPath," in dispatcher
        assert "file_name: inferredFileName," in dispatcher
        assert "file_type: inferredFileType," in dispatcher
        assert "current_file: currentFile ? {" in dispatcher
        assert "task_context: taskContext," in dispatcher
        assert "target: !!(targetFile && normalizeTaskPath(targetFile.path || targetFile.name || '') === currentPathKey)," in dispatcher
        assert "const explicitSelectionText = String(explicitTaskPayload.selection || '').trim();" in dispatcher
        assert "if (!explicitSelectionText && Object.prototype.hasOwnProperty.call(explicitTaskPayload, 'current_file')) {" in dispatcher
        assert "if (inferredExplicitCurrentFile) explicitTaskPayload['current_file'] = inferredExplicitCurrentFile;" not in dispatcher
        assert "overrideOptions.inferred_target_file_type = canonicalTaskFileType(targetFile);" in dispatcher
        assert "const taskContext = buildTaskContextPackage({" in dispatcher
        assert "model_mode: typeof options.getModelMode === 'function' ? options.getModelMode() : 'cloud'," in dispatcher
        assert "model_id: typeof options.getSelectedCloudModelId === 'function' ? options.getSelectedCloudModelId() : ''," in dispatcher
        assert "options: overrideOptions," in dispatcher
        assert "history: typeof options.getConversationHistory === 'function'" in dispatcher
        assert "const payload = buildFileTaskPayload(context.text, context.pinnedSelText, context.pinnedSelSource, context);" in dispatcher
        assert "return Promise.resolve(streamFileTask({" in dispatcher
        assert "payload," in dispatcher
        assert "taskTurnMetadataFromLoadingEl(loadingEl)" in dispatcher

    def test_workspace_send_message_falls_back_to_live_selection_when_context_bar_has_unpinned_selection(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")

        send_start = assistant.index("window.WA.sendMessage = () => {")
        send_end = assistant.index("// ── Auto-save", send_start)
        send_block = assistant[send_start:send_end]

        assert "const liveSelection = !pinnedSel ? _getLiveEditorSelectionForAI() : null;" in send_block
        assert "const liveSelectionContext = !pinnedSel && liveSelection" in send_block
        assert "const explicitSelection = pinnedSel || liveSelectionContext;" in send_block
        assert "const pinnedSelText = _selectionContextText(explicitSelection);" in send_block
        assert "const pinnedSelSource = _selectionContextSourceLabel(explicitSelection);" in send_block
        assert "state.lastPinnedSel = explicitSelection || null;" in send_block

    def test_run_python_in_sandbox_reports_locked_attached_target_as_write_blocked(self, tmp_path, monkeypatch):
        from app.core.agent import task_tools

        source_path = tmp_path / "humanise!_revised.docx"
        source_path.write_text("before", encoding="utf-8")

        original_copy2 = task_tools.shutil.copy2

        def selective_copy2(src, dst, *args, **kwargs):
            if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(str(source_path))):
                raise PermissionError(32, "locked", str(source_path))
            return original_copy2(src, dst, *args, **kwargs)

        monkeypatch.setattr(task_tools.shutil, "copy2", selective_copy2)

        result = task_tools.run_python_in_sandbox(
            (
                "from pathlib import Path\n"
                f"p = Path(TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
                "p.write_text('after', encoding='utf-8')\n"
                f"print('KOTO_MODIFIED:' + TASK_SANDBOX_FILE_PATHS[{source_path.name!r}])\n"
            ),
            timeout=10,
            task_files=[{"path": str(source_path), "name": source_path.name}],
        )

        assert result.get("status") == "write_blocked"
        assert "当前不可写" in result.get("summary", "")
        assert result.get("suggested_next_step")
        assert not result.get("__koto_modified__")
        assert source_path.read_text(encoding="utf-8") == "before"

    def test_workspace_dispatcher_marks_short_task_critiques_as_followup_context(self):
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "function latestCompletedFileTaskTurn()" in dispatcher
        assert "function looksLikeDiagnosticLead(text)" in dispatcher
        assert "function looksLikeTaskFollowupContinuation(text)" in dispatcher
        assert "function inferTaskFollowupAction(text)" in dispatcher
        assert "function looksLikeTaskCritique(text)" in dispatcher
        assert "function buildTaskFollowupContext(text)" in dispatcher
        assert "kind: 'review_last_task'" in dispatcher
        assert "followup_action: inferTaskFollowupAction(text)" in dispatcher
        assert "if (looksLikeTaskFollowupContinuation(source)) return true;" in dispatcher
        assert "function looksLikeExplicitNewTask(text)" not in dispatcher
        assert "overrideOptions.followup_context = followupContext;" in dispatcher
        assert "const previousTaskVisibleTrace = previewText(previousTaskTurn.task_visible_trace || '', 1600);" in dispatcher
        assert "任务轨迹：" in dispatcher
        assert "context.previous_run_id = previousRunId;" in dispatcher
        assert "context.previous_task_mode = previousTaskMode;" in dispatcher
        assert "window.WA.compactTaskContract(previousTaskTurn.task_contract, { text: previewText })" in dispatcher
        assert "window.WA.decodeTaskContract(dataset.taskContract || '')" in dispatcher
        assert "context.previous_task_contract_id = previousTaskContractId;" in dispatcher
        assert "context.previous_task_contract = previousTaskContract;" in dispatcher
        assert "context.previous_task_context = previousTaskContext;" in dispatcher
        assert "context.previous_task_file_changes = previousTaskFileChanges;" in dispatcher

    def test_workspace_dispatcher_infers_followup_apply_and_improve_actions(self):
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "return 'apply';" in dispatcher
        assert "return 'improve';" in dispatcher
        assert "looksLikePreviousTaskReference(source) && /(?:直接应用|应用建议|按上一轮|按建议|按方案|apply)/i.test(source)" in dispatcher

    def test_workspace_task_cards_offer_run_bound_followup_actions(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "window.WA.beginTaskResultFollowup = (details) => {" in assistant
        assert "state._pendingTaskFollowupContext = followupContext;" in assistant
        assert "options: pendingTaskFollowupContext ? { followup_context: pendingTaskFollowupContext } : {}," in assistant
        assert "请把上一轮已经给出的建议直接应用到目标文件；沿用同一任务上下文继续写回，不要重新从头分析。" in assistant
        assert "previous_task_output_mode: String(payload.output_mode || '').trim()," in assistant
        assert "previous_task_intent_strategy: String(payload.intent_strategy || '').trim()," in assistant
        assert "previous_task_intent_can_apply" in assistant
        assert "previous_task_intent_requires_confirmation" in assistant
        assert "window.WA.compactTaskContract(payload.task_contract)" in assistant
        assert "previous_task_contract_id = previousTaskContract.contract_id;" in assistant
        assert "followupContext.previous_task_contract = previousTaskContract;" in assistant
        assert "function taskResultActionsHtml(card) {" in task_renderer
        assert 'data-task-followup-action="apply"' in task_renderer
        assert 'data-task-followup-action="question"' in task_renderer
        assert 'data-task-followup-action="improve"' in task_renderer
        assert "window.WA.beginTaskResultFollowup({" in task_renderer
        assert "window.WA.compactTaskContract = compactTaskContract;" in task_renderer
        assert "window.WA.encodeTaskContract = encodeTaskContract;" in task_renderer
        assert "window.WA.decodeTaskContract = decodeTaskContract;" in task_renderer
        assert "output_mode: card.dataset.taskOutputMode || ''," in task_renderer
        assert "intent_strategy: card.dataset.taskIntentStrategy || ''," in task_renderer
        assert "intent_can_apply: boolAttr(card.dataset.taskIntentCanApply)," in task_renderer
        assert "intent_requires_confirmation: boolAttr(card.dataset.taskIntentRequiresConfirmation)," in task_renderer
        assert "task_contract: taskContract && typeof taskContract === 'object' ? taskContract : null," in task_renderer
        assert "task_context: taskPayload && typeof taskPayload === 'object' ? taskPayload.task_context : null," in task_renderer
        assert "file_changes: Array.isArray(taskState.fileChanges) ? taskState.fileChanges.slice(-8) : []," in task_renderer
        assert "card.dataset.taskId" in task_renderer
        assert "task_id: card.dataset.taskId || ''," in task_renderer
        assert "card.dataset.taskRunId" in task_renderer
        assert "window.WA.encodeTaskContract(taskContract)" in task_renderer
        assert "window.WA.decodeTaskContract(card.dataset.taskContract || '')" in task_renderer
        assert "previous_task_file_changes = previousTaskFileChanges" in assistant
        assert "followupContext.previous_task_context = previousTaskContext;" in assistant

    def test_workspace_task_followups_freeze_compact_request_payload(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function compactFollowupTaskFile(file) {" in dispatcher
        assert "function compactFollowupTaskPayload(payload) {" in dispatcher
        assert "function compactPendingResumePayload(payload) {" in dispatcher
        assert "const files = Array.isArray(payload.files)" in dispatcher
        assert "payload.files.map((file) => compactFollowupTaskFile(file)).filter(Boolean)" in dispatcher
        assert "const currentFile = compactFollowupTaskFile(payload.current_file);" in dispatcher
        assert "const task = String(payload.task || '').trim();" in dispatcher
        assert "payload.options && typeof payload.options === 'object'" in dispatcher
        assert "payload.options.batch_control && typeof payload.options.batch_control === 'object'" in dispatcher
        assert "function setTaskFollowupPayload(loadingEl, payload) {" in dispatcher
        assert "function setPendingTaskResumePayload(loadingEl, payload) {" in dispatcher
        assert "const compactPayload = compactFollowupTaskPayload(payload);" in dispatcher
        assert "const compactPayload = compactPendingResumePayload(payload);" in dispatcher
        assert "loadingEl.dataset.taskFollowupPayload = encodeURIComponent(JSON.stringify(compactPayload));" in dispatcher
        assert "loadingEl.dataset.taskPendingResumePayload = encodeURIComponent(JSON.stringify(compactPayload));" in dispatcher
        assert "metadata.task_request_payload = JSON.parse(decodeURIComponent(String(dataset.taskFollowupPayload || '').trim()));" in dispatcher
        assert "setTaskFollowupPayload(loadingEl, payload);" in dispatcher
        assert "setPendingTaskResumePayload(loadingEl, payload);" in dispatcher
        assert "setTaskFollowupPayload(card, payload);" in dispatcher
        assert "setPendingTaskResumePayload(card, payload);" in dispatcher
        assert "const taskPayload = decodeTaskRequestPayload(card.dataset.taskFollowupPayload || '');" in task_renderer
        assert "const pendingTaskPayload = decodeTaskRequestPayload(card.dataset.taskPendingResumePayload || '');" in task_renderer
        assert "taskPayload," in task_renderer
        assert "pendingTaskPayload," in task_renderer
        assert "const rawTaskPayload = payload.taskPayload && typeof payload.taskPayload === 'object'" in assistant
        assert "const pendingTaskPayload = payload.pendingTaskPayload && typeof payload.pendingTaskPayload === 'object'" in assistant
        assert "const taskPayload = (!completedTask && pendingTaskPayload) ? pendingTaskPayload : rawTaskPayload;" in assistant
        assert "state._pendingTaskPayload = taskPayload;" in assistant

    def test_workspace_task_dispatcher_builds_stepwise_resume_memory(self):
        """Long file tasks that ask to pause after every step should carry an explicit next-step plan memory."""
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "function taskRequestsStepwiseConfirmation(text) {" in dispatcher
        assert "每完成一步" in dispatcher
        assert "function ensureStepwiseResumePayload(payload, text) {" in dispatcher
        assert "policy: 'confirm_each_step'" in dispatcher
        assert "original_task: String(existingBatchControl.original_task || text || cloned.task || '').trim()" in dispatcher
        assert "followupContext.kind = followupContext.kind || 'stepwise_task_resume';" in dispatcher
        assert "followupContext.followup_action = 'resume';" in dispatcher
        assert "context.continuity.stepwise = {" in dispatcher
        assert "resume_label: '继续下一步'" in dispatcher
        assert "if (taskRequestsStepwiseConfirmation(text) && !payload.options.batch_control)" in dispatcher

    def test_workspace_task_followup_binding_drops_for_unrelated_new_input(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")

        assert "function _looksLikeTaskResultFollowupReference(text) {" in assistant
        assert "function _looksLikeShortTaskResultFollowup(text, action) {" in assistant
        assert "function _shouldKeepPendingTaskResultFollowup(text, followupContext, defaultPrompt) {" in assistant
        assert "function _clearPendingTaskResultFollowupBinding(noticeText) {" in assistant
        assert "state._pendingTaskFollowupPrompt = defaultPrompt;" in assistant
        assert "state._pendingTaskFollowupPrompt = null;" in assistant
        assert "state._pendingTaskFollowupContext = null;" in assistant
        assert "state._pendingTaskPayload = null;" in assistant
        assert "if (pendingTaskFollowupContext && !_shouldKeepPendingTaskResultFollowup(text, pendingTaskFollowupContext, state._pendingTaskFollowupPrompt)) {" in assistant
        assert "pendingTaskPayload = null;" in assistant
        assert "pendingTaskFollowupContext = null;" in assistant
        assert "_clearPendingTaskResultFollowupBinding('已清除上一任务绑定，当前消息将按新任务处理。');" in assistant
        assert "(?:上一轮|上一版|上一次|上次|前一轮|刚才|这次|这个任务|这次任务|这个结果|这次结果|上一轮结果|上一轮建议|上一轮处理|当前结果|当前方案|这个方案|你的建议|前面的建议|刚才的结果|前一个结果)" in assistant

    def test_workspace_local_file_pickers_support_text_documents(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        standalone = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        main = Path("web/templates/index.html").read_text(encoding="utf-8")

        assert "'text/plain': ['.txt']" in assistant
        assert "'text/markdown': ['.md', '.markdown']" in assistant
        assert "'text/csv': ['.csv']" in assistant
        assert "'application/json': ['.json']" in assistant
        assert "['docx', 'xlsx', 'pptx', 'pdf', 'txt', 'md', 'markdown', 'csv', 'json'].includes(ext)" in assistant
        assert 'accept=".docx,.xlsx,.pptx,.pdf,.txt,.md,.markdown,.csv,.json,.png,.jpg,.jpeg,.gif,.bmp,.webp,.svg"' in standalone
        assert 'accept=".docx,.xlsx,.pptx,.pdf,.txt,.md,.markdown,.csv,.json"' in standalone
        assert 'accept=".docx,.xlsx,.pptx,.pdf,.txt,.md,.markdown,.csv,.json,.png,.jpg,.jpeg,.gif,.bmp,.webp,.svg"' in main
        assert 'accept=".docx,.xlsx,.pptx,.pdf,.txt,.md,.markdown,.csv,.json"' in main

    def test_workspace_file_task_renderer_is_extracted(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        ai_results = Path("web/static/js/workspace-ai-results.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        conversation = Path("web/static/js/workspace-ai-conversation.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        asset_partial = Path("web/templates/_workspace_asset_scripts.html").read_text(encoding="utf-8")
        standalone = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        main = Path("web/templates/index.html").read_text(encoding="utf-8")

        assert "window.WA.streamFileTask" in renderer
        assert "stream" + "White" + "box" + "Task" not in renderer
        assert "fetch('/api/editor/ai/task-stream'" in renderer
        assert "window.WA.createWorkspaceAiResultsRuntime" in ai_results
        assert "window.WA.createWorkspaceQuickActionRuntime" in quick_actions
        assert "window.WA.createWorkspaceAiConversation" in conversation
        assert "model' || value === 'ai'" in conversation
        assert "window.WA.createTaskDispatcher" in dispatcher
        assert "if (!_waAiResultsRuntime && window.WA && typeof window.WA.createWorkspaceAiResultsRuntime === 'function')" in assistant
        assert "if (!_waConversationRuntime && window.WA && typeof window.WA.createWorkspaceAiConversation === 'function')" in assistant
        assert "window.WA.hydrateAiHistory" in assistant
        assert "if (!_waQuickActionRuntime && window.WA && typeof window.WA.createWorkspaceQuickActionRuntime === 'function')" in assistant
        assert "_waQuickActionRuntime.attachDispatcher(_waTaskDispatcher);" in assistant
        assert "if (!_waTaskDispatcher && window.WA && typeof window.WA.createTaskDispatcher === 'function')" in assistant
        assert "fetch('/api/editor/ai/task-stream'" not in assistant
        assert "{% include '_workspace_asset_scripts.html' %}" in standalone
        assert "{% include '_workspace_asset_scripts.html' %}" in main
        assert "workspace-ai-task.js" in asset_partial
        assert "workspace-ai-results.js" in asset_partial
        assert "workspace-ai-quick-actions.js" in asset_partial
        assert "workspace-ai-conversation.js" in asset_partial
        assert "workspace-task-dispatcher.js" in asset_partial
        assert "docx-review-layout.js" in asset_partial
        assert "doc-agent-ui.js" not in standalone
        assert "wa-doc-agent-phases" not in standalone
        assert "wa-inline-ai" not in main
        assert "data-dm=\"inline\"" not in main

    def test_workspace_dispatcher_exposes_extension_registration_points(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")

        assert "registerMessageRoute" in dispatcher
        assert "registerQuickActionHandler" in dispatcher
        assert "registerQuickActionHandler," in dispatcher
        assert "registerQuickActionKeyword" in dispatcher
        assert "registerAction(definition)" in quick_actions
        assert "window.WA.registerTaskQuickAction" in assistant
        assert "window.WA.registerTaskEntryRoute" in assistant
        assert "window.WA.registerTaskActionHandler" in assistant
        assert "window.WA.registerTaskActionKeyword" in assistant

    def test_workspace_default_quick_actions_use_direct_action_ids(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        standalone = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")
        main = Path("web/templates/index.html").read_text(encoding="utf-8")

        for source in (assistant, standalone, main):
            assert "onclick=\"WA.sendQuickAction('润色')\"" in source
            assert "onclick=\"WA.sendQuickAction('翻译')\"" in source
            assert "onclick=\"WA.sendQuickAction('总结')\"" in source
            assert "onclick=\"WA.sendQuickAction('检查')\"" in source
            assert "onclick=\"WA.sendQuickAction('可视化')\"" in source
            assert "WA.quickAction('请帮我翻译当前内容" not in source

    def test_workspace_default_quick_actions_can_fall_back_to_full_document(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")

        assert "const _WA_FULL_DOC_QUICK_ACTIONS = new Set(['润色', '翻译', '总结', '续写', '检查']);" in assistant
        assert re.search(r"action: '润色',[\s\S]*?fullDocument: true,[\s\S]*?fileTaskMode: 'proposal'", quick_actions)
        assert re.search(r"action: '翻译',[\s\S]*?readOnly: true,[\s\S]*?fullDocument: true,[\s\S]*?fileTaskMode: 'simple'", quick_actions)

    def test_workspace_dispatcher_records_assistant_turns_for_task_history(self):
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "function appendAssistantConversationTurn(text, metadata)" in dispatcher
        assert "options.appendAssistantTurn(content" in dispatcher
        assert "options.getConversationHistory()" in dispatcher
        assert "function finalizeFileTaskTurn(taskTurnId, loadingEl, result, fallbackStatus, skipModelContext)" in dispatcher
        assert "options.syncAssistantTaskTurn(taskTurnId, turnMetadata);" in dispatcher
        assert "appendAssistantConversationTurn(assistantText, turnMetadata);" in dispatcher
        assert "const assistantText = finalizeFileTaskTurn(taskTurnId, loadingEl, streamResult, 'done', false);" in dispatcher

    def test_workspace_conversation_runtime_uses_in_memory_session_store_and_model_context(self):
        conversation = Path("web/static/js/workspace-ai-conversation.js").read_text(encoding="utf-8")

        assert "function normalizeRole(role)" in conversation
        assert "if (value === 'model' || value === 'ai') return 'assistant';" in conversation
        assert "const sessionStore = new Map();" in conversation
        assert "function normalizedSessionId(rawSessionId)" in conversation
        assert "async function hydrate(params)" in conversation
        assert "renderHistory(sessionTurns(sessionId));" in conversation
        assert "query.set('session_id', sessionId);" not in conversation
        assert "renderHistory(history.map" not in conversation
        assert "function getHistoryForModel(limit)" in conversation
        assert "turn.status !== 'error'" in conversation

    def test_workspace_assistant_uses_runtime_scoped_ai_session(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")

        assert "_linkedAiSessionId" not in assistant
        assert "function _waConversationDocId()" not in assistant
        assert "const _WA_RUNTIME_SESSION_ID = (() => {" in assistant
        assert "sessionStorage.getItem('wa_runtime_session_id')" in assistant
        assert "sessionStorage.setItem('wa_runtime_session_id', generated);" in assistant
        assert "workspace_runtime_" in assistant
        assert "return _WA_RUNTIME_SESSION_ID;" in assistant
        assert "return 'workspace_' + (state.fileId || 'default');" not in assistant
        assert "window.WA.openAiSessionFromSidebar" not in assistant
        assert "window.WA.renameLinkedAiSession" not in assistant
        assert "window.WA.removeLinkedAiSession" not in assistant
        assert "getConversationHistory: () => _waConversationRuntime && typeof _waConversationRuntime.getHistoryForModel === 'function'" in assistant

    def test_workspace_assistant_boot_hydrates_ai_history_for_recovery(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")

        assert "_initWorkspaceAiRuntimes();\n  _hydrateAiConversation(true).catch((error) => console.warn('[WA] AI history hydrate failed:', error));" in assistant
        assert "window.WA.hydrateAiHistory = (force = true) => _hydrateAiConversation(force);" in assistant

    def test_workspace_file_reload_does_not_force_task_replay_recovery(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")

        switch_start = assistant.find("async function _switchToTab(path) {")
        switch_end = assistant.find("function _ensureOutlineToggleBtn()", switch_start)
        assert switch_start != -1 and switch_end != -1
        switch_block = assistant[switch_start:switch_end]
        assert "_hydrateAiConversation(false).catch((error) => console.warn('[WA] AI history hydrate failed:', error));" in switch_block
        assert "_hydrateAiConversation(true).catch((error) => console.warn('[WA] AI history hydrate failed:', error));" not in switch_block

        apply_start = assistant.find("async function _applyFileJson(json, wsPath, fsHandle) {")
        apply_end = assistant.find("/** Map tool names to user-friendly labels for the agent step timeline. */", apply_start)
        assert apply_start != -1 and apply_end != -1
        apply_block = assistant[apply_start:apply_end]
        assert "_hydrateAiConversation(false).catch((error) => console.warn('[WA] AI history hydrate failed:', error));" in apply_block
        assert "_hydrateAiConversation(true).catch((error) => console.warn('[WA] AI history hydrate failed:', error));" not in apply_block
        assert "if (!force || state.isLoading) return turns;" in assistant
        assert "if (!force && state._activeTaskReconnectors.has(taskId)) continue;" in assistant

    def test_workspace_task_cards_are_snapshotted_for_runtime_history_restore(self):
        conversation = Path("web/static/js/workspace-ai-conversation.js").read_text(encoding="utf-8")
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "turn.task_card_snapshot && window.WA && typeof window.WA.restoreTaskRunCard === 'function'" in conversation
        assert "task_card_snapshot:" in conversation
        assert "function beginAssistantTaskTurn(metadata) {" in conversation
        assert "function syncAssistantTaskTurn(turnId, metadata) {" in conversation
        assert "文件任务已启动，正在建立执行流…" in dispatcher
        assert "loadingEl.classList.contains('wa-task-run')" in conversation
        assert "if (loadingEl && loadingEl.isConnected) {" in conversation
        assert "const taskTurn = typeof options.beginAssistantTaskTurn === 'function'" in dispatcher
        assert "onTaskCardSnapshot: (card) => {" in dispatcher
        assert "options.syncAssistantTaskTurn(taskTurnId" in dispatcher
        assert "beginAssistantTaskTurn: (metadata) => _waConversationRuntime && typeof _waConversationRuntime.beginAssistantTaskTurn === 'function'" in assistant
        assert "syncAssistantTaskTurn: (turnId, metadata) => _waConversationRuntime && typeof _waConversationRuntime.syncAssistantTaskTurn === 'function'" in assistant
        assert "window.WA.restoreTaskRunCard = function restoreTaskRunCard(snapshot) {" in task_renderer
        assert "if (typeof opts.onTaskCardSnapshot === 'function') {" in task_renderer
        assert "return attachRunCardBehavior(card);" in task_renderer

    def test_workspace_task_turn_metadata_keeps_task_id_for_restore(self):
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "if (dataset.taskId) metadata.task_id = String(dataset.taskId || '').trim();" in dispatcher

    def test_workspace_assistant_recovers_active_file_tasks_via_task_api(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "const sources = ['file_task'];" in assistant
        assert "_listRecoverableFileTasks('running')" in assistant
        assert "_listRecoverableFileTasks('waiting')" in assistant
        assert "window.WA.resumePersistedFileTask({" in assistant
        assert "window.WA.resumePersistedFileTask = function resumePersistedFileTask(options) {" in task_renderer
        assert "resumePersisted" + "White" + "box" + "Task" not in task_renderer
        assert "new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/stream?replay=${replay ? 'true' : 'false'}`)" in task_renderer
        assert "function rawTaskEventFromProgressEnvelope(progressEvent, taskId) {" in task_renderer

    def test_workspace_waiting_task_resume_uses_task_api_and_resets_seq_per_run(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "window.WA.resumePersistedTaskArtifact = async (details) => {" in assistant
        assert "fetch(`/api/tasks/${encodeURIComponent(taskId)}/resume`" in assistant
        assert "return window.WA.resumeTaskArtifact(payload);" in assistant
        assert "replay: false," in assistant
        assert "typeof window.WA.resumePersistedTaskArtifact === 'function'" in task_renderer
        assert "loadingEl: card," in task_renderer
        assert "const incomingRunId = String(evt && evt.run_id || '').trim();" in task_renderer
        assert "incomingRunId && currentRunId && incomingRunId !== currentRunId" in task_renderer
        assert "state.lastEventSeq = 0;" in task_renderer
        assert "evt.type !== 'ui.message'" not in task_renderer

    def test_workspace_dispatcher_infers_compare_target_from_revised_docx_names(self):
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")

        assert "const COMPARE_TASK_HINTS = ['对比', '比较', '对照', '差异', '区别', '不同', 'compare', 'diff', 'difference'];" in dispatcher
        assert "const REVISED_TARGET_NAME_HINTS = ['_revised', '-revised', ' revised', 'revised_', '修订', '修改', '批注', 'annotated', 'reviewed', 'commented', 'markup'];" in dispatcher
        assert "function inferCompareAnnotatedTargetFile(text, files) {" in dispatcher
        assert "const compareTarget = inferCompareAnnotatedTargetFile(text, files);" in dispatcher
        assert "if (compareTarget) return compareTarget;" in dispatcher
        assert "if (!hasWriteTargetHint(text)) return null;" in dispatcher

    def test_workspace_task_terminal_result_is_finalized_in_one_frontend_path(self):
        dispatcher = Path("web/static/js/workspace-task-dispatcher.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function taskTerminalResult(card, fallbackSummary) {" in task_renderer
        assert "return terminalResult;" in task_renderer
        assert "function finalizeFileTaskTurn(taskTurnId, loadingEl, result, fallbackStatus, skipModelContext) {" in dispatcher
        assert "const assistantText = finalizeFileTaskTurn(taskTurnId, loadingEl, streamResult, 'done', false);" in dispatcher
        assert "finalizeFileTaskTurn(taskTurnId, loadingEl, {" in dispatcher

    def test_workspace_task_renderer_updates_terminal_final_summary_through_one_helper(self):
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function updateFinalSummaryFromTerminalEvent(evt, currentSummary) {" in task_renderer
        assert "if (evt.type !== 'run.finished' && evt.type !== 'multi_target.finished') return currentSummary || '';" in task_renderer
        assert "async function processFileTaskStreamEvent(card, evt, opts, msgs, currentSummary) {" in task_renderer
        assert task_renderer.count("finalSummary = await processFileTaskStreamEvent(card, evt, opts, msgs, finalSummary);") == 2
        assert task_renderer.count("handleEvent(card, evt);") == 1
        assert task_renderer.count("state.lastEventSeq = Math.max(lastSeq, seq);") == 1
        assert "finalSummary = payload.summary || ''" not in task_renderer
        assert "finalSummary = payload.summary || finalSummary" not in task_renderer

    def test_main_chat_filters_workspace_assistant_sessions(self):
        app_js = Path("web/static/js/app.js").read_text(encoding="utf-8")
        sessions_bp = Path("web/blueprints/sessions.py").read_text(encoding="utf-8")

        assert "_isWorkspaceAssistantSession" not in app_js
        assert "_maybeOpenWorkspaceAssistantSession" not in app_js
        assert "_notifyWorkspaceAssistantSessionRenamed" not in app_js
        assert "_notifyWorkspaceAssistantSessionDeleted" not in app_js
        assert "def _is_workspace_assistant_session(filename: str) -> bool:" in sessions_bp
        assert "if not _is_workspace_assistant_session(session)" in sessions_bp

    def test_workspace_task_renderer_drops_loaded_memory_context_step(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "type === 'memory.loaded'" not in renderer
        assert "已读取相关对话记忆" not in renderer
        assert 'wa-task-chip ok">记忆' not in renderer

    def test_workspace_task_renderer_uses_segment_wording_for_review_progress(self):
        renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "本分段 +${addedCount} 条" in renderer
        assert "查看本分段建议" in renderer
        assert "第 ${chunkIndex}/${chunkTotal} 个分段已完成" in renderer
        assert "本段 +${addedCount} 条" not in renderer
        assert "查看本段建议" not in renderer
        assert "第 ${chunkIndex}/${chunkTotal} 段已完成" not in renderer

    def test_workspace_quick_actions_do_not_keep_editor_ai_stream_fallback(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        quick_actions = Path("web/static/js/workspace-ai-quick-actions.js").read_text(encoding="utf-8")
        assert "async function _sendViaEditorActionSSE(payload)" not in src
        assert "window.WA.sendQuickAction = (action) => {" in src
        assert "getConversationHistory: () => _waConversationRuntime && typeof _waConversationRuntime.getHistoryForModel === 'function'" in src
        assert "action: editorAction" not in quick_actions
        assert "/api/editor/ai/stream" not in quick_actions
        assert "sendEditorAction(payload) {" not in quick_actions
        assert "window.WA.quickAction =" in src

    def test_workspace_retired_inline_ai_entrypoints_are_removed(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "window.WA.sendInlineMessage = () =>" not in src
        assert "window.WA.inlineQuickAction = (text) =>" not in src
        assert "window.WA.handleInlineInputKeydown = (e) =>" not in src
        assert "window.WA.setAIDisplayMode = (mode) =>" not in src
        assert "wa_ai_display_mode" not in src

    def test_workspace_topic_ai_entrypoints_are_removed(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "window.WA.extractTopics = async () =>" not in src
        assert "window.WA._topicClick = (btn) =>" not in src
        assert "window.WA.closeTopicBar = () =>" not in src
        assert "wa-topic-chips-bar" not in src

    def test_workspace_templates_do_not_expose_retired_inline_ai_controls(self):
        embedded_html = Path("web/templates/index.html").read_text(encoding="utf-8")
        standalone_html = Path("web/templates/workspace_assistant.html").read_text(encoding="utf-8")

        assert not Path("web/static/js/doc-agent-ui.js").exists()
        assert not Path("web/static/css/doc-agent.css").exists()
        assert "wa-inline-ai" not in embedded_html
        assert "WA.sendInlineMessage()" not in embedded_html
        assert "WA.inlineQuickAction(" not in embedded_html
        assert "data-dm=\"inline\"" not in embedded_html
        assert "doc-agent.css" not in standalone_html
        assert "doc-agent-ui.js" not in standalone_html
        assert "wa-doc-agent-phases" not in standalone_html

    def test_workspace_input_autopin_requires_live_editor_selection(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        assert "function _getLiveEditorSelectionForAI()" in src
        input_start = src.find("const _waInput = $('wa-user-input');")
        input_end = src.find("// ── Split.js Init", input_start)
        assert input_start != -1 and input_end != -1
        input_section = src[input_start:input_end]
        assert "const liveSelection = _getLiveEditorSelectionForAI();" in input_section
        assert "if (liveSelection) {" in input_section
        assert "_pinSelectionChip(liveSelection);" in input_section

    def test_workspace_proposal_card_filters_duplicate_rationale_text(self):
        """Proposal cards should hide rationale text when it just repeats original/proposed content."""
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        results = Path("web/static/js/workspace-ai-results.js").read_text(encoding="utf-8")
        assert "function _getProposalRationaleText(proposal)" in assistant
        assert "_waAiResultsRuntime.getProposalRationaleText(proposal)" not in assistant
        assert "function getProposalRationaleText(proposal)" in results
        assert "rationaleKey === originalKey || rationaleKey === proposedKey" in results

    def test_workspace_ai_review_tool_calls_route_into_docx_review_surface(self):
        assistant = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        results = Path("web/static/js/workspace-ai-results.js").read_text(encoding="utf-8")
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")
        assert "window.WA.applyStructuredDocToolCall" in assistant
        assert "window.WA.applyStructuredReviewChangePayload" in assistant
        assert "window.WA.applyStructuredDocToolCall(proposal.tool_call" in results
        assert "window.WA.applyStructuredDocToolCall(toolCall" in results
        assert "function isReviewChangePayload(payload) {" in task_renderer
        assert "window.WA.applyStructuredReviewChangePayload(payload" in task_renderer

    def test_workspace_task_renderer_reuses_one_review_change_helper(self):
        task_renderer = Path("web/static/js/workspace-ai-task.js").read_text(encoding="utf-8")

        assert "function isReviewChangePayload(payload) {" in task_renderer
        assert task_renderer.count("isReviewChangePayload(payload)") == 5
        assert task_renderer.count("payload.operation === 'annotate_file' || payload.operation === 'annotate' || Number(payload.annotations_added || 0) > 0") == 1

    def test_workspace_proposal_buttons_stay_single_line_and_equal_width(self):
        """Proposal action buttons should share width and keep labels on one line."""
        css = read_workspace_stylesheet_contract()
        assert ".wa-proposal-actions .wa-proposal-btn" in css
        assert "flex: 1 1 0;" in css
        assert "white-space: nowrap;" in css
        assert "min-height: 34px;" in css

    def test_agent_loop_sends_sanitized_proposal_summary(self):
        """Structured proposal summary should reuse the sanitized note, not raw clean_text."""
        src = Path("app/core/agent/agent_loop.py").read_text(encoding="utf-8")
        assert 'proposal_summary = proposals[0].get("rationale", "")' in src
        assert 'yield evt_proposal(proposals, proposal_summary)' in src

    def test_workspace_assistant_docx_helpers_stay_outside_browser_ctx(self):
        src = Path("web/static/js/workspace-assistant.js").read_text(encoding="utf-8")
        show_ctx_idx = src.index("window.WA._showBrowserCtx")
        for symbol in (
            "function _cloneSerializable(",
            "function _getDocxRenderOpts(",
            "function _cacheDocxTabState(",
            "function _serializeEditorForTab(",
        ):
            symbol_idx = src.index(symbol)
            assert symbol_idx < show_ctx_idx, (
                f"{symbol} must remain top-level before window.WA._showBrowserCtx "
                "so DOCX open/render helpers stay visible outside the browser context menu handler"
            )



