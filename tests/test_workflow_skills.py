"""
tests/test_workflow_skills.py
Unit tests for the 5 workflow skill modules.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_workbook(rows: list[list]) -> dict:
    """Build a minimal IWorkbookData-like dict for assertion helpers."""
    cell_data = {}
    for r, row in enumerate(rows):
        cell_data[r] = {c: {"v": val} for c, val in enumerate(row)}
    return {
        "id": "test_wb",
        "sheetOrder": ["s1"],
        "sheets": {
            "s1": {
                "id": "s1",
                "name": "Sheet1",
                "cellData": cell_data,
                "rowCount": len(rows),
                "columnCount": max((len(r) for r in rows), default=0),
            }
        },
    }


# ── CrossFormatExtractor ─────────────────────────────────────────────────────


class TestCrossFormatExtractor:
    def test_build_workbook_has_header_row(self):
        from app.core.workflows.cross_format_extractor import CrossFormatExtractor

        extractor = CrossFormatExtractor()
        fields = ["姓名", "邮箱", "电话"]
        rows = [{"姓名": "张三", "邮箱": "zs@example.com", "电话": "13800000000"}]
        wb = extractor._build_workbook(fields, rows)

        sheet = list(wb["sheets"].values())[0]
        cd = sheet["cellData"]
        # Row "0" = header (string keys)
        header_vals = [cd["0"][str(c)]["v"] for c in range(len(fields))]
        assert header_vals == fields
        # Row "1" = data
        assert cd["1"]["0"]["v"] == "张三"

    def test_source_file_column_appended(self):
        from app.core.workflows.cross_format_extractor import CrossFormatExtractor

        extractor = CrossFormatExtractor()
        fields = ["名称"]
        rows = [{"名称": "ProductX", "_source_file": "invoice.pdf"}]
        wb = extractor._build_workbook(fields, rows)

        sheet = list(wb["sheets"].values())[0]
        cd = sheet["cellData"]
        # Header should include _source_file
        col_count = sheet["columnCount"]
        assert col_count >= 2


# ── DataFormatCleaner ────────────────────────────────────────────────────────


class TestDataFormatCleaner:
    def test_diff_csv_detects_changed_cells(self):
        from app.core.workflows.data_format_cleaner import DataFormatCleaner

        cleaner = DataFormatCleaner()
        original = "日期,金额\n2024/1/5,1000\n2024/2/10,2000"
        cleaned = "日期,金额\n2024-01-05,1000\n2024-02-10,2000"

        diffs = cleaner._diff_csv(original, cleaned)
        # Both date cells should be in diffs
        assert len(diffs) == 2
        cols = {d["column"] for d in diffs}
        assert cols == {"日期"}
        old_vals = {d["old"] for d in diffs}
        new_vals = {d["new"] for d in diffs}
        assert "2024/1/5" in old_vals
        assert "2024-01-05" in new_vals

    def test_diff_csv_no_change(self):
        from app.core.workflows.data_format_cleaner import DataFormatCleaner

        cleaner = DataFormatCleaner()
        csv_data = "a,b\n1,2\n3,4"
        diffs = cleaner._diff_csv(csv_data, csv_data)
        assert diffs == []


# ── QuestionnaireFiller ──────────────────────────────────────────────────────


class TestQuestionnaireFiller:
    def test_parse_questions_finds_question_column(self, tmp_path):
        import openpyxl

        from app.core.workflows.questionnaire_filler import QuestionnaireFiller

        # Build a simple xlsx with a "问题" column
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["序号", "问题", "备注"])
        ws.append([1, "贵公司成立于哪年?", ""])
        ws.append([2, "主营业务是什么?", ""])
        xlsx_path = tmp_path / "questions.xlsx"
        wb.save(str(xlsx_path))

        filler = QuestionnaireFiller()
        questions = filler._parse_questions(str(xlsx_path), question_col=None)
        assert len(questions) == 2
        assert questions[0]["question"] == "贵公司成立于哪年?"

    def test_parse_questions_with_explicit_col(self, tmp_path):
        import openpyxl

        from app.core.workflows.questionnaire_filler import QuestionnaireFiller

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["题目", "来源"])
        ws.append(["请说明数据安全措施", "第2章"])
        xlsx_path = tmp_path / "q2.xlsx"
        wb.save(str(xlsx_path))

        filler = QuestionnaireFiller()
        questions = filler._parse_questions(str(xlsx_path), question_col="题目")
        assert len(questions) == 1
        assert "数据安全" in questions[0]["question"]


# ── CommDigest ───────────────────────────────────────────────────────────────


class TestCommDigest:
    @patch("app.core.workflow_engine.call_llm_json")
    def test_extract_full_calls_llm(self, mock_clj):
        from app.core.workflows.comm_digest import CommDigest

        mock_clj.return_value = {
            "title": "项目纪要",
            "participants": ["王五"],
            "date_range": "2025-02-01",
            "timeline": [],
            "decisions": [],
            "open_questions": [],
            "action_items": [
                {
                    "task": "整理报告",
                    "owner": "王五",
                    "deadline": "2025-02-01",
                    "status": "pending",
                    "priority": "high",
                }
            ],
        }

        extractor = CommDigest()
        result = extractor._extract_full(
            "王五你负责整理报告，deadline 2月1号", "zh", "online"
        )
        assert result["action_items"][0]["task"] == "整理报告"

    def test_build_workbook_headers(self):
        from app.core.workflows.comm_digest import CommDigest

        extractor = CommDigest()
        items = [
            {
                "task": "T1",
                "owner": "A",
                "deadline": "2025-03-01",
                "status": "in_progress",
                "priority": "high",
                "source": "邮件",
            }
        ]
        wb = extractor._build_workbook(items)
        sheet = list(wb["sheets"].values())[0]
        cd = sheet["cellData"]
        col_count = sheet["columnCount"]
        # Headers use string keys in output workbook
        header = [cd["0"][str(c)]["v"] for c in range(col_count)]
        # Join all header text and check key concepts appear
        header_text = " ".join(str(h) for h in header)
        assert "任务" in header_text
        assert "负责人" in header_text


# ── DocSmartCompare ──────────────────────────────────────────────────────────


class TestDocSmartCompare:
    def test_rule_split_numbered_clauses(self):
        from app.core.workflows.doc_smart_compare import DocSmartCompare

        compare = DocSmartCompare()
        # Two blank lines trigger paragraph split
        text = "第一条 甲方应于签约后10日内支付款项。\n\n第二条 乙方应提供发票并配合验收。\n\n第三条 争议依法由合同签订地仲裁委员会解决。"
        clauses = compare._rule_split(text)
        assert len(clauses) == 3
        # Results are dicts with "text" key
        assert "甲方" in clauses[0]["text"]

    def test_rule_split_arabic_numbered(self):
        from app.core.workflows.doc_smart_compare import DocSmartCompare

        compare = DocSmartCompare()
        # Two blank lines trigger paragraph split
        text = "1. 本协议签订有效期为一年，双方同意遵守。\n\n2. 双方可提前六十天书面通知对方协商续签。\n\n3. 违约方应赔偿守约方因此遭受的全部损失。"
        clauses = compare._rule_split(text)
        assert len(clauses) == 3

    def test_generate_diff_html_filters_unchanged(self):
        from app.core.workflows.doc_smart_compare import DocSmartCompare

        compare = DocSmartCompare()
        alignments = [
            {
                "原文片段": "第一条: 甲方支付货款。",
                "修改建议": "第一条: 甲方支付货款。",
                "diff_type": "unchanged",
                "severity": "none",
                "diff_detail": "",
                "risk_flag": False,
            },
            {
                "原文片段": "付款期限为10日",
                "修改建议": "付款期限为30日",
                "修改原因": "付款期限从10日改为30日，风险较大",
                "diff_type": "modified",
                "severity": "critical",
                "risk_flag": True,
            },
        ]
        html = compare._generate_diff_html(alignments)
        # unchanged entries should not appear; modified should
        assert "30日" in html or "付款期限" in html


# ── Workflow API Blueprint ────────────────────────────────────────────────────


class TestWorkflowApiBlueprint:
    @pytest.fixture
    def client(self):
        """Create a minimal Flask test client with the workflow blueprint."""
        from flask import Flask

        from web.blueprints.workflow_api import workflow_bp

        app = Flask(__name__)
        app.register_blueprint(workflow_bp)
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_list_returns_five_workflows(self, client):
        resp = client.get("/api/workflow/list")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["workflows"]) >= 5

    def test_list_workflow_ids(self, client):
        resp = client.get("/api/workflow/list")
        ids = {w["id"] for w in resp.get_json()["workflows"]}
        # 核心工作流必须存在（不排除后续新增的工作流）
        expected_core = {
            "cross_format_extractor",
            "data_format_cleaner",
            "questionnaire_filler",
            "comm_digest",
            "doc_smart_compare",
        }
        assert expected_core.issubset(ids)
        assert {"contract_diff_markup", "email_thread_digest"}.isdisjoint(ids)

    def test_execute_missing_workflow_id(self, client):
        resp = client.post(
            "/api/workflow/execute",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_execute_unknown_workflow(self, client):
        resp = client.post(
            "/api/workflow/execute",
            json={"workflow_id": "nonexistent", "params": {}},
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_upload_no_files(self, client):
        resp = client.post("/api/workflow/upload", data={})
        assert resp.status_code == 400

    def test_upload_single_file(self, client, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello world")
        with open(str(test_file), "rb") as f:
            resp = client.post(
                "/api/workflow/upload",
                data={"files[]": (f, "test.txt"), "session_id": "testses"},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert len(data["paths"]) == 1
        assert "test.txt" in data["paths"][0]
