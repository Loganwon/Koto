import json

import pytest


def test_verify_task_completion_uses_structured_docx_table_metadata():
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="把 xlsx 表格加入 docx",
            file_states=json.dumps([
                {"path": "report.docx", "exists": True, "modified": True, "preview": "..."}
            ], ensure_ascii=False),
            file_changes=json.dumps([
                {
                    "path": "report.docx",
                    "operation": "insert_excel_as_docx_table",
                    "sheet": "汇总表",
                    "rows_written": 200,
                    "columns_written": 4,
                }
            ], ensure_ascii=False),
            target_path="report.docx",
        )
    )

    assert result["completed"] is True
    assert "文件已成功修改：report.docx" in result["summary"]
    assert "工作表“汇总表”" in result["summary"]
    assert "200 行 × 4 列" in result["summary"]
    assert any(item["criterion"] == "all_tracked_files_modified" and item["passed"] is True for item in result["criteria_results"])
    assert any(item["criterion"] == "target_file_hit" and item["passed"] is True for item in result["criteria_results"])


def test_verify_task_completion_uses_structured_docx_image_metadata():
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="把图表加入 docx",
            file_states=json.dumps([
                {"path": "report.docx", "exists": True, "modified": True, "preview": "..."}
            ], ensure_ascii=False),
            file_changes=json.dumps([
                {
                    "path": "report.docx",
                    "operation": "insert_image_into_docx",
                    "image_name": "chart.png",
                    "images_inserted": 1,
                    "caption": "收入与利润趋势",
                }
            ], ensure_ascii=False),
            target_path="report.docx",
        )
    )

    assert result["completed"] is True
    assert "文件已成功修改：report.docx" in result["summary"]
    assert "已插入 1 张图片" in result["summary"]
    assert "chart.png" in result["summary"]


def test_verify_task_completion_rejects_table_only_result_when_task_requires_summary_text():
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="整理 xlsx 中的财务预测，并加入 docx",
            file_states=json.dumps([
                {"path": "report.docx", "exists": True, "modified": True, "preview": "..."}
            ], ensure_ascii=False),
            file_changes=json.dumps([
                {
                    "path": "report.docx",
                    "operation": "insert_excel_as_docx_table",
                    "sheet": "P&L",
                    "rows_written": 50,
                    "columns_written": 13,
                }
            ], ensure_ascii=False),
            target_path="report.docx",
        )
    )

    assert result["completed"] is False
    assert "当前只写入了表格" in result["summary"]
    assert result["remaining_steps"] == ["先提炼关键结论，再用 write_docx_content 把摘要/说明写入目标 DOCX"]
    assert any(item["criterion"] == "docx_narrative_write_present" and item["passed"] is False for item in result["criteria_results"])


def test_verify_task_completion_detects_target_mismatch_from_structured_changes():
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="修改目标报告",
            file_states=json.dumps([
                {"path": "other.docx", "exists": True, "modified": True, "preview": "..."}
            ], ensure_ascii=False),
            file_changes=json.dumps([
                {
                    "path": "other.docx",
                    "operation": "write_docx_content",
                    "paragraphs_written": 1,
                }
            ], ensure_ascii=False),
            target_path="report.docx",
        )
    )

    assert result["completed"] is False
    assert "未命中目标文件：report.docx" in result["summary"]
    assert result["remaining_steps"] == ["把结果写入 report.docx"]
    assert result["criteria_results"] == [
        {
            "criterion": "target_file_hit",
            "passed": False,
            "detail": "已修改 other.docx，但未命中目标文件：report.docx",
            "priority": "critical",
        }
    ]


def test_verify_task_completion_rejects_locked_target_fallback_copy_as_original_write():
    from app.core.agent.task_tools import verify_task_completion

    result = json.loads(
        verify_task_completion(
            task_description="把 xlsx 表格加入 docx",
            file_states=json.dumps([
                {"path": "report.koto-copy.docx", "exists": True, "modified": True, "preview": "..."}
            ], ensure_ascii=False),
            file_changes=json.dumps([
                {
                    "path": "report.koto-copy.docx",
                    "operation": "insert_excel_as_docx_table",
                    "sheet": "汇总表",
                    "rows_written": 200,
                    "columns_written": 4,
                    "original_target_path": "report.docx",
                    "fallback_copy": True,
                    "blocked_target": True,
                }
            ], ensure_ascii=False),
            target_path="report.docx",
        )
    )

    assert result["completed"] is False
    assert "目标文件尚未完成修改：report.docx" in result["summary"]
    assert "report.koto-copy.docx" in result["summary"]
    assert result["remaining_steps"] == ["检查 report.docx 的文件权限；如果文件正在被占用，关闭相关程序后重新写回原文件"]


def test_verify_task_completion_matches_workspace_relative_target_to_absolute_change(tmp_path, monkeypatch):
    import app.core.agent.task_tools as task_tools

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    from app.core.agent.task_tools import verify_task_completion

    target_path = tmp_path / "notes.txt"
    target_path.write_text("updated", encoding="utf-8")

    result = json.loads(
        verify_task_completion(
            task_description="润色当前文本并写回原文件",
            file_states=json.dumps([
                {"path": str(target_path), "exists": True, "modified": True, "preview": "updated"}
            ], ensure_ascii=False),
            file_changes=json.dumps([
                {
                    "path": str(target_path),
                    "operation": "run_python_code",
                    "summary": "Python 代码更新了 notes.txt",
                }
            ], ensure_ascii=False),
            target_path="notes.txt",
        )
    )

    assert result["completed"] is True
    assert "文件已成功修改：notes.txt" in result["summary"]


def test_annotate_file_returns_standard_file_change_payload(tmp_path, monkeypatch):
    import app.core.agent.task_tools as task_tools
    from app.core.agent.file_task_tool_catalog import parse_file_change

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    notes_path = tmp_path / "notes.txt"
    notes_path.write_text("alpha beta", encoding="utf-8")

    result = task_tools.annotate_file(
        "notes.txt",
        [{"range_start": 0, "range_end": 5, "comment": "需要核对"}],
    )
    payload = json.loads(result)
    change = parse_file_change("annotate_file", {"path": "notes.txt"}, result)

    assert payload["success"] is True
    assert payload["path"] == "notes.txt"
    assert payload["operation"] == "annotate_file"
    assert payload["change_type"] == "annotate"
    assert payload["annotations_added"] == 1
    assert change["path"] == "notes.txt"
    assert change["operation"] == "annotate_file"
    assert change["annotations_added"] == 1


def test_annotate_file_docx_requirement_returns_streaming_native_tool_result(tmp_path, monkeypatch):
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    import app.core.agent.task_tools as task_tools
    from app.core.agent.file_task_contract import FileTaskToolStreamChunk, FileTaskToolStreamResult
    from app.core.agent.file_task_tool_gateway import FileTaskToolContext, FileTaskToolGateway

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))
    docx_path = tmp_path / "draft.docx"
    docx_path.write_bytes(b"PK\x03\x04")

    captured = {}

    def fake_stream_request_as_tool(request, *, workspace_root="", gemini_client=None):
        captured["request"] = request
        captured["workspace_root"] = workspace_root
        captured["gemini_client"] = gemini_client
        return FileTaskToolStreamResult(
            chunks=[
                FileTaskToolStreamChunk(
                    kind="event",
                    event_type="step_progress",
                    payload={
                        "detail": "已写入 1/2 条修订",
                        "file_updated": True,
                        "path": "draft.docx",
                        "file_path": "draft.docx",
                        "applied": 1,
                    },
                ),
                FileTaskToolStreamChunk(
                    kind="result",
                    payload={
                        "success": True,
                        "path": "draft.docx",
                        "file_path": "draft.docx",
                        "annotations_added": 2,
                        "updated_in_place": True,
                    },
                ),
            ]
        )

    monkeypatch.setattr(bridge, "stream_request_as_tool", fake_stream_request_as_tool)

    gateway = FileTaskToolGateway(
        context=FileTaskToolContext(
            task_files=[{"path": "draft.docx", "type": "docx", "target": True}],
            workspace_root=str(tmp_path),
            gemini_client="gemini-client",
            request_context={
                "task": "请批注不通顺的地方",
                "target_path": "draft.docx",
                "model_mode": "cloud",
                "model_id": "gemini-2.5-pro",
            },
        )
    )

    result = gateway.execute(
        "annotate_file",
        {"path": "draft.docx", "annotations": "[]", "requirement": "请批注不通顺的地方"},
    )

    assert isinstance(result, FileTaskToolStreamResult)

    chunks = list(result.chunks)
    progress_chunk = next(
        chunk for chunk in chunks if chunk.kind == "event" and chunk.event_type == "step_progress" and chunk.payload.get("file_updated")
    )
    final_chunk = chunks[-1]

    assert captured["gemini_client"] == "gemini-client"
    assert captured["workspace_root"] == str(tmp_path)
    assert captured["request"].target_path == "draft.docx"
    assert captured["request"].task == "请批注不通顺的地方"
    assert captured["request"].model_id == "gemini-2.5-pro"
    assert any(file_info.type == "docx" and file_info.target for file_info in captured["request"].files)
    assert progress_chunk.payload["path"] == "draft.docx"
    assert final_chunk.kind == "result"
    assert final_chunk.payload["path"] == "draft.docx"
    assert final_chunk.payload["annotations_added"] == 2
    assert final_chunk.payload["updated_in_place"] is True


def test_clear_docx_review_marks_removes_docx_comments_and_registers_file_change(tmp_path, monkeypatch):
    docx_module = pytest.importorskip("docx")

    import app.core.agent.task_tools as task_tools
    from app.core.agent.file_task_tool_catalog import parse_file_change
    from web.track_changes_editor import TrackChangesEditor

    monkeypatch.setattr(task_tools, "_WORKSPACE_ROOT", str(tmp_path))

    docx_path = tmp_path / "draft.docx"
    document = docx_module.Document()
    document.add_paragraph("第一段用于清除批注测试。")
    document.save(docx_path)

    editor = TrackChangesEditor(author="Koto Test")
    applied = editor.apply_comment_changes(
        str(docx_path),
        [{"原文片段": "第一段用于清除批注测试。", "修改后文本": "建议改写", "修改原因": "测试"}],
    )

    assert applied["applied"] == 1

    import zipfile

    with zipfile.ZipFile(docx_path) as archive:
        assert "word/comments.xml" in archive.namelist()
        assert "commentReference" in archive.read("word/document.xml").decode("utf-8", errors="ignore")

    result = task_tools.clear_docx_review_marks("draft.docx", scope="comments")
    payload = json.loads(result)
    change = parse_file_change("clear_docx_review_marks", {"path": "draft.docx", "scope": "comments"}, result)

    assert payload["success"] is True
    assert payload["path"] == "draft.docx"
    assert payload["operation"] == "clear_docx_review_marks"
    assert payload["scope"] == "comments"
    assert payload["comments_removed"] >= 1
    assert change["path"] == "draft.docx"
    assert change["operation"] == "clear_docx_review_marks"
    assert change["comments_removed"] >= 1

    with zipfile.ZipFile(docx_path) as archive:
        names = archive.namelist()
        document_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    assert "word/comments.xml" not in names
    assert "commentRangeStart" not in document_xml
    assert "commentRangeEnd" not in document_xml
    assert "commentReference" not in document_xml


def test_task_tools_plugin_exposes_clear_docx_review_marks_tool():
    from app.core.agent.task_tools import TaskToolsPlugin

    tool_names = {tool["name"] for tool in TaskToolsPlugin(task_files=[{"path": "draft.docx", "type": "docx"}]).get_tools()}

    assert "clear_docx_review_marks" in tool_names


def test_normalize_docx_review_clear_scope_accepts_annotation_synonyms():
    import app.core.agent.task_tools as task_tools

    assert task_tools._normalize_docx_review_clear_scope("标注") == "comments"
    assert task_tools._normalize_docx_review_clear_scope("annotation") == "comments"


def test_annotate_file_pdf_docx_requirement_uses_bridge_streaming_tool_result(tmp_path, monkeypatch):
    import app.core.agent.file_task_doc_annotate_bridge as bridge
    from app.core.agent.file_task_contract import FileTaskToolStreamChunk, FileTaskToolStreamResult
    from app.core.agent.file_task_tool_gateway import FileTaskToolContext, FileTaskToolGateway

    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    docx_path = tmp_path / "translation.docx"
    docx_path.write_bytes(b"PK\x03\x04")

    captured = {}

    def fake_stream_request_as_tool(request, *, workspace_root="", gemini_client=None):
        captured["request"] = request
        captured["workspace_root"] = workspace_root
        captured["gemini_client"] = gemini_client
        return FileTaskToolStreamResult(
            chunks=[
                FileTaskToolStreamChunk(kind="event", event_type="plan.confirmed", payload={"summary": "按 3 批执行"}),
                FileTaskToolStreamChunk(
                    kind="result",
                    payload={
                        "success": True,
                        "summary": "文件较大，已生成 3 批执行计划，等待确认开始第 1/3 批。",
                        "awaiting_confirmation": True,
                    },
                ),
            ]
        )

    monkeypatch.setattr(bridge, "stream_request_as_tool", fake_stream_request_as_tool)

    gateway = FileTaskToolGateway(
        context=FileTaskToolContext(
            task_files=[
                {"path": str(pdf_path), "type": "pdf"},
                {"path": str(docx_path), "type": "docx", "target": True},
            ],
            workspace_root=str(tmp_path),
            gemini_client="gemini-client",
            request_context={
                "task": "PDF是原文，docx文件是现有翻译稿。文件较大，请拆成多个分段来处理。",
                "target_path": str(docx_path),
                "options": {},
                "model_mode": "cloud",
                "model_id": "gemini-2.5-pro",
            },
        )
    )

    result = gateway.execute(
        "annotate_file",
        {"path": str(docx_path), "annotations": "[]", "requirement": "根据原文审校译稿并拆分执行"},
    )

    assert isinstance(result, FileTaskToolStreamResult)
    assert captured["workspace_root"] == str(tmp_path)
    assert captured["gemini_client"] == "gemini-client"
    assert captured["request"].target_path == str(docx_path)
    assert any(file_info.type == "pdf" for file_info in captured["request"].files)
    assert any(file_info.type == "docx" and file_info.target for file_info in captured["request"].files)


def test_file_snapshot_treats_missing_new_target_as_empty_snapshot(tmp_path):
    from app.core.file.multi_file_coordinator import FileSnapshot

    missing_path = tmp_path / "new_target.txt"
    snapshot = FileSnapshot.from_file(str(missing_path))

    assert snapshot.path == str(missing_path)
    assert snapshot.content == ""
    assert snapshot.content_hash