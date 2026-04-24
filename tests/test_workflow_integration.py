"""
tests/test_workflow_integration.py
Integration tests verifying workflow API is registered and end-to-end reachable.
"""

from __future__ import annotations

import io
import json
import pytest
from unittest.mock import patch, MagicMock


# ── Fixture: full Flask app with all blueprints ──────────────────────────────

@pytest.fixture(scope="module")
def full_client():
    """Create a test client using the real Koto Flask app (with workflow_bp registered)."""
    from flask import Flask
    from web.blueprints.workflow_api import workflow_bp

    app = Flask(__name__)
    app.register_blueprint(workflow_bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Workflow API registration tests ──────────────────────────────────────────

class TestWorkflowRegistration:
    """Verify the workflow blueprint is properly set up and reachable."""

    def test_list_endpoint_returns_200(self, full_client):
        resp = full_client.get("/api/workflow/list")
        assert resp.status_code == 200

    def test_list_returns_five_workflows(self, full_client):
        resp = full_client.get("/api/workflow/list")
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["workflows"]) >= 5

    def test_all_workflow_ids_present(self, full_client):
        resp = full_client.get("/api/workflow/list")
        ids = {w["id"] for w in resp.get_json()["workflows"]}
        # 核心工作流必须存在
        expected_core = {
            "cross_format_extractor",
            "data_format_cleaner",
            "questionnaire_filler",
            "comm_digest",
            "doc_smart_compare",
        }
        assert expected_core.issubset(ids)
        assert {"contract_diff_markup", "email_thread_digest"}.isdisjoint(ids)

    def test_workflows_have_required_fields(self, full_client):
        resp = full_client.get("/api/workflow/list")
        for wf in resp.get_json()["workflows"]:
            assert "id" in wf
            assert "name" in wf
            assert "description" in wf
            # params_schema is optional for simpler workflows
            assert "icon" in wf

    def test_execute_rejects_empty_body(self, full_client):
        resp = full_client.post(
            "/api/workflow/execute",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_execute_rejects_unknown_workflow(self, full_client):
        resp = full_client.post(
            "/api/workflow/execute",
            json={"workflow_id": "nonexistent", "params": {}},
            content_type="application/json",
        )
        assert resp.status_code == 404


# ── File upload tests ────────────────────────────────────────────────────────

class TestWorkflowUpload:
    def test_upload_returns_paths(self, full_client):
        data = {
            "files[]": (io.BytesIO(b"hello world"), "test.txt"),
        }
        resp = full_client.post(
            "/api/workflow/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert len(body["paths"]) == 1
        assert "test.txt" in body["paths"][0]

    def test_upload_no_files_returns_400(self, full_client):
        resp = full_client.post(
            "/api/workflow/upload",
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400

    def test_upload_multiple_files(self, full_client):
        data = {
            "files[]": [
                (io.BytesIO(b"file1"), "a.pdf"),
                (io.BytesIO(b"file2"), "b.docx"),
            ],
        }
        resp = full_client.post(
            "/api/workflow/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["paths"]) == 2


# ── Executor instantiation tests ─────────────────────────────────────────────

class TestExecutorFactory:
    """Verify each workflow executor can be instantiated without errors."""

    @pytest.mark.parametrize("workflow_id", [
        "cross_format_extractor",
        "data_format_cleaner",
        "questionnaire_filler",
        "doc_smart_compare",
        "comm_digest",
    ])
    def test_executor_instantiates(self, workflow_id):
        from web.blueprints.workflow_api import _get_executor
        executor = _get_executor(workflow_id)
        assert executor is not None
        assert hasattr(executor, "execute")
        assert hasattr(executor, "run")

    def test_unknown_executor_returns_none(self):
        from web.blueprints.workflow_api import _get_executor
        assert _get_executor("nonexistent") is None

    @pytest.mark.parametrize("workflow_id", [
        "contract_diff_markup",
        "email_thread_digest",
    ])
    def test_legacy_executor_ids_removed(self, workflow_id):
        from web.blueprints.workflow_api import _get_executor
        assert _get_executor(workflow_id) is None


# ── SSE format tests ─────────────────────────────────────────────────────────

class TestSSEEventFormat:
    """Verify SSE event builders produce correct format."""

    def test_sse_events_are_valid_json(self):
        from app.core.workflow_engine import (
            sse_status, sse_progress, sse_step_start, sse_step_done,
            sse_output, sse_error, sse_done,
        )
        events = [
            sse_status("处理中"),
            sse_progress(1, 5, "第一步"),
            sse_step_start("parse", "解析文件"),
            sse_step_done("parse", "解析文件"),
            sse_output("markdown", "# 结果", "输出"),
            sse_error("出错了"),
            sse_done("完成"),
        ]
        for evt in events:
            assert evt.startswith("data: ")
            assert evt.endswith("\n\n")
            payload = json.loads(evt[6:].strip())
            assert "type" in payload


# ── Workflow executor core methods (non-LLM) ────────────────────────────────

class TestCrossFormatExtractorMethods:
    def test_build_workbook_structure(self):
        from app.core.workflows.cross_format_extractor import CrossFormatExtractor
        ext = CrossFormatExtractor()
        fields = ["名称", "金额"]
        rows = [{"名称": "A", "金额": "100"}, {"名称": "B", "金额": "200"}]
        wb = ext._build_workbook(fields, rows)
        assert "sheets" in wb
        sheet = list(wb["sheets"].values())[0]
        assert sheet["rowCount"] >= 3  # header + 2 data rows


class TestDataFormatCleanerMethods:
    def test_diff_csv_identifies_changes(self):
        from app.core.workflows.data_format_cleaner import DataFormatCleaner
        cleaner = DataFormatCleaner()
        original = "名称,日期\n张三,2024/1/5\n李四,2024/2/10"
        cleaned = "名称,日期\n张三,2024-01-05\n李四,2024-02-10"
        diffs = cleaner._diff_csv(original, cleaned)
        assert len(diffs) == 2
        assert all(d["column"] == "日期" for d in diffs)


class TestDocSmartCompareMethods:
    def test_rule_split_produces_clauses(self):
        from app.core.workflows.doc_smart_compare import DocSmartCompare
        compare = DocSmartCompare()
        # Need >= 3 paragraphs (separated by \n\n) for paragraph split
        text = "第一条 甲方应于签约后10日内支付款项。\n\n第二条 乙方应提供发票并配合验收。\n\n第三条 争议依法由合同签订地仲裁委员会解决。"
        clauses = compare._rule_split(text)
        assert len(clauses) == 3

    def test_generate_diff_html(self):
        from app.core.workflows.doc_smart_compare import DocSmartCompare
        compare = DocSmartCompare()
        alignments = [
            {"原文片段": "第一条 甲方支付货款十万元整",
             "修改建议": "第一条 甲方支付货款三万元整",
             "修改原因": "金额从十万改为三万",
             "diff_type": "modified", "severity": "critical", "risk_flag": True},
        ]
        html = compare._generate_diff_html(alignments)
        assert "甲方" in html
        assert "金额" in html


class TestCommDigestMethods:
    def test_build_workbook_has_headers(self):
        from app.core.workflows.comm_digest import CommDigest
        ext = CommDigest()
        items = [{"task": "做X", "owner": "A", "deadline": "2025-01-01",
                  "status": "pending", "priority": "high", "source": "邮件"}]
        wb = ext._build_workbook(items)
        sheet = list(wb["sheets"].values())[0]
        assert sheet["columnCount"] >= 5


class TestQuestionnaireFillerMethods:
    def test_parse_questions(self, tmp_path):
        import openpyxl
        from app.core.workflows.questionnaire_filler import QuestionnaireFiller

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["问题", "答案"])
        ws.append(["你是谁?", ""])
        ws.append(["做什么?", ""])
        path = tmp_path / "q.xlsx"
        wb.save(str(path))

        filler = QuestionnaireFiller()
        questions = filler._parse_questions(str(path), question_col=None)
        assert len(questions) == 2
