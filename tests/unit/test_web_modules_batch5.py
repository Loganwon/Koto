"""
Unit tests for web modules batch 5:
  - ProactiveTriggerSystem (proactive_trigger.py)
  - ParallelExecutor classes (parallel_executor.py)
  - ProcessedFileNetwork (processed_file_network.py)
  - FileQualityChecker classes (file_quality_checker.py)
  - SearchEngine (search_engine.py)

Each test class covers constructors, core logic, and edge cases with mocked I/O.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, mock_open, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# ProactiveTriggerSystem
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestProactiveTrigger:
    """Tests for app.core.services.proactive_trigger.ProactiveTriggerSystem."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.db_path = str(tmp_path / "triggers.db")

    def _make_system(self, **kwargs):
        from app.core.services.proactive_trigger import ProactiveTriggerSystem

        return ProactiveTriggerSystem(db_path=self.db_path, **kwargs)

    # --- init & database ---

    def test_init_creates_database_tables(self):
        """Init should create trigger_history, trigger_config, trigger_effectiveness tables."""
        self._make_system()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "trigger_history" in tables
        assert "trigger_config" in tables
        assert "trigger_effectiveness" in tables
        assert "trigger_parameters" in tables

    def test_builtin_triggers_registered(self):
        """Init should register multiple built-in triggers."""
        system = self._make_system()
        assert len(system.triggers) >= 10
        assert "periodic_check_suggestions" in system.triggers
        assert "emergency_file_loss_risk" in system.triggers

    def test_register_trigger_custom(self):
        """register_trigger should add custom trigger to registry and db."""
        from app.core.services.proactive_trigger import TriggerCondition, TriggerType

        system = self._make_system()
        cond = TriggerCondition(
            trigger_id="custom_test",
            trigger_type=TriggerType.EVENT,
            condition_func=lambda uid: None,
            priority=5,
            cooldown_minutes=60,
            description="test trigger",
        )
        system.register_trigger(cond)
        assert "custom_test" in system.triggers

        # Verify it's persisted in database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT trigger_id FROM trigger_config WHERE trigger_id = 'custom_test'"
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None

    def test_should_trigger_disabled(self):
        """Disabled trigger should not fire."""
        system = self._make_system()
        system.triggers["periodic_check_suggestions"].enabled = False
        assert system.should_trigger("periodic_check_suggestions") is False

    def test_should_trigger_cooldown(self):
        """Trigger within cooldown period should not fire."""
        system = self._make_system()
        trigger_id = "periodic_check_suggestions"
        system.last_trigger_times[trigger_id] = datetime.now()
        assert system.should_trigger(trigger_id) is False

    def test_should_trigger_unknown_id(self):
        """Unknown trigger_id returns False."""
        system = self._make_system()
        assert system.should_trigger("nonexistent_trigger") is False

    def test_should_trigger_past_cooldown(self):
        """Trigger past cooldown period should fire."""
        system = self._make_system()
        trigger_id = "periodic_check_suggestions"
        cooldown = system.triggers[trigger_id].cooldown_minutes
        system.last_trigger_times[trigger_id] = datetime.now() - timedelta(
            minutes=cooldown + 1
        )
        assert system.should_trigger(trigger_id) is True

    def test_list_triggers_sorted_by_priority(self):
        """list_triggers returns triggers sorted by descending priority."""
        system = self._make_system()
        triggers = system.list_triggers()
        assert len(triggers) > 0
        priorities = [t["priority"] for t in triggers]
        assert priorities == sorted(priorities, reverse=True)

    def test_update_trigger_config(self):
        """update_trigger_config modifies the in-memory and db config."""
        system = self._make_system()
        trigger_id = "periodic_morning_greeting"
        result = system.update_trigger_config(trigger_id, enabled=False, priority=1)
        assert result is True
        assert system.triggers[trigger_id].enabled is False
        assert system.triggers[trigger_id].priority == 1

    def test_update_trigger_config_nonexistent(self):
        """update_trigger_config returns False for unknown trigger_id."""
        system = self._make_system()
        assert system.update_trigger_config("no_such_trigger", enabled=True) is False

    def test_update_and_get_trigger_params(self):
        """update_trigger_params merges new params and persists them."""
        system = self._make_system()
        tid = "periodic_check_suggestions"
        original = system.get_trigger_params(tid)
        system.update_trigger_params(tid, {"custom_key": 42})
        updated = system.get_trigger_params(tid)
        assert updated["custom_key"] == 42
        # Original keys should still exist
        for k in original:
            assert k in updated

    def test_evaluate_interaction_need_no_triggers_fire(self):
        """When all triggers return None, evaluate_interaction_need returns None."""
        system = self._make_system()
        # Disable all triggers
        for t in system.triggers.values():
            t.enabled = False
        result = system.evaluate_interaction_need()
        assert result is None

    def test_determine_interaction_type_emergency(self):
        """Emergency trigger type should return ALERT."""
        from app.core.services.proactive_trigger import InteractionType, TriggerType

        system = self._make_system()
        itype = system._determine_interaction_type(TriggerType.EMERGENCY, 0.5, 0.5)
        assert itype == InteractionType.ALERT

    def test_determine_interaction_type_high_urgency(self):
        """High urgency (>=0.8) returns ALERT regardless of trigger type."""
        from app.core.services.proactive_trigger import InteractionType, TriggerType

        system = self._make_system()
        itype = system._determine_interaction_type(TriggerType.PERIODIC, 0.9, 0.5)
        assert itype == InteractionType.ALERT

    def test_determine_interaction_type_pattern(self):
        """Pattern trigger type with medium urgency returns QUESTION."""
        from app.core.services.proactive_trigger import InteractionType, TriggerType

        system = self._make_system()
        itype = system._determine_interaction_type(TriggerType.PATTERN, 0.4, 0.4)
        assert itype == InteractionType.QUESTION

    def test_calculate_disturbance_cost_late_night(self):
        """Disturbance cost should increase during late night hours."""
        from app.core.services.proactive_trigger import TriggerCondition, TriggerType

        system = self._make_system()
        trigger = TriggerCondition(
            trigger_id="test",
            trigger_type=TriggerType.PERIODIC,
            condition_func=lambda uid: None,
            priority=5,
            cooldown_minutes=60,
        )
        with patch("app.core.services.proactive_trigger.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 2, 0, 0)  # 2am
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            cost = system._calculate_disturbance_cost("user1", trigger)
            assert cost >= 0.3  # late night penalty


# ═══════════════════════════════════════════════════════════════════════════════
# ParallelExecutor
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.unit
class TestProcessedFileNetwork:
    """Tests for app.core.services.processed_file_network.ProcessedFileNetwork."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path
        self.db_path = str(tmp_path / "file_network.db")
        self.workspace = str(tmp_path / "workspace")
        os.makedirs(self.workspace, exist_ok=True)

    def _make_network(self):
        from app.core.services.processed_file_network import ProcessedFileNetwork

        return ProcessedFileNetwork(db_path=self.db_path, workspace_dir=self.workspace)

    def _create_test_file(
        self, name="test.txt", content="Hello World file content here for testing"
    ):
        path = os.path.join(self.workspace, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_init_creates_tables(self):
        self._make_network()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "file_records" in tables
        assert "processing_history" in tables
        assert "file_relations" in tables
        assert "text_snippets" in tables

    def test_register_file_success(self):
        net = self._make_network()
        path = self._create_test_file()
        result = net.register_file(path)
        assert result["success"] is True
        assert "file_id" in result

    def test_register_file_nonexistent(self):
        net = self._make_network()
        result = net.register_file("/nonexistent/file.txt")
        assert result["success"] is False
        assert "error" in result

    def test_register_file_idempotent(self):
        """Registering the same file twice should succeed (INSERT OR REPLACE)."""
        net = self._make_network()
        path = self._create_test_file()
        r1 = net.register_file(path)
        r2 = net.register_file(path)
        assert r1["file_id"] == r2["file_id"]

    def test_record_processing(self):
        net = self._make_network()
        path = self._create_test_file()
        result = net.record_processing(
            file_path=path,
            operation="annotate",
            changes_count=5,
            duration_seconds=1.5,
        )
        assert result["success"] is True
        assert "record_id" in result

    def test_create_relation(self):
        net = self._make_network()
        f1 = self._create_test_file("a.txt", "file a")
        f2 = self._create_test_file("b.txt", "file b")
        r1 = net.register_file(f1)
        r2 = net.register_file(f2)
        rel = net.create_relation(r1["file_id"], r2["file_id"], "related_to")
        assert rel["success"] is True

    def test_search_files_by_type(self):
        net = self._make_network()
        self._create_test_file("doc.txt", "some content")
        net.register_file(os.path.join(self.workspace, "doc.txt"))
        result = net.search_files(file_type="txt")
        assert result["success"] is True
        assert result["total_count"] >= 1

    def test_search_files_empty(self):
        net = self._make_network()
        result = net.search_files(file_type="pdf")
        assert result["success"] is True
        assert result["total_count"] == 0

    def test_get_file_network_graph(self):
        net = self._make_network()
        path = self._create_test_file()
        reg = net.register_file(path)
        result = net.get_file_network(reg["file_id"], depth=1)
        assert result["success"] is True
        assert result["node_count"] >= 1

    def test_get_file_network_nonexistent(self):
        net = self._make_network()
        result = net.get_file_network("nonexistent_id")
        assert result["success"] is False

    def test_get_statistics(self):
        net = self._make_network()
        path = self._create_test_file()
        net.register_file(path)
        stats = net.get_statistics()
        assert stats["success"] is True
        assert stats["statistics"]["total_files"] >= 1

    def test_native_open_file_helper_removed(self):
        net = self._make_network()
        assert not hasattr(net, "open_file")

    def test_dataclass_file_record_defaults(self):
        from app.core.services.processed_file_network import FileRecord

        fr = FileRecord(
            file_id="id1",
            path="/a/b",
            name="b",
            file_type="txt",
            size=100,
            created_at="2024-01-01",
            modified_at="2024-01-01",
            indexed_at="2024-01-01",
            content_hash="abc",
        )
        assert fr.tags == []

    def test_dataclass_file_relation_defaults(self):
        from app.core.services.processed_file_network import FileRelation

        rel = FileRelation(
            relation_id="r1",
            source_file_id="f1",
            target_file_id="f2",
            relation_type="derived_from",
            created_at="2024-01-01",
        )
        assert rel.metadata == {}


# FileQualityChecker
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestFileQualityChecker:
    """Tests for file_quality_checker: strip_markdown, ContentSanitizer, evaluators, gate."""

    # --- strip_markdown_for_export ---

    def test_strip_markdown_bold(self):
        from web.documents.file_quality_checker import strip_markdown_for_export

        assert "hello" in strip_markdown_for_export("**hello**")
        assert "**" not in strip_markdown_for_export("**hello**")

    def test_strip_markdown_code_block(self):
        from web.documents.file_quality_checker import strip_markdown_for_export

        text = "```python\nprint('hi')\n```"
        result = strip_markdown_for_export(text)
        assert "```" not in result
        assert "print" in result

    def test_strip_markdown_heading(self):
        from web.documents.file_quality_checker import strip_markdown_for_export

        result = strip_markdown_for_export("## My Title")
        assert "##" not in result
        assert "My Title" in result

    def test_strip_markdown_link(self):
        from web.documents.file_quality_checker import strip_markdown_for_export

        result = strip_markdown_for_export("[Click here](https://example.com)")
        assert "Click here" in result
        assert "https://example.com" not in result

    def test_strip_markdown_empty_input(self):
        from web.documents.file_quality_checker import strip_markdown_for_export

        assert strip_markdown_for_export("") == ""
        assert strip_markdown_for_export(None) is None

    # --- strip_markdown_from_cell ---

    def test_strip_markdown_from_cell_bold(self):
        from web.documents.file_quality_checker import strip_markdown_from_cell

        assert strip_markdown_from_cell("**test**") == "test"

    def test_strip_markdown_from_cell_empty(self):
        from web.documents.file_quality_checker import strip_markdown_from_cell

        assert strip_markdown_from_cell("") == ""
        assert strip_markdown_from_cell(None) is None

    # --- detect_markdown_in_export ---

    def test_detect_markdown_in_export_finds_bold(self):
        from web.documents.file_quality_checker import detect_markdown_in_export

        issues = detect_markdown_in_export("This is **bold** text")
        assert any("加粗" in i for i in issues)

    def test_detect_markdown_in_export_clean_text(self):
        from web.documents.file_quality_checker import detect_markdown_in_export

        issues = detect_markdown_in_export("Plain text without markdown")
        assert len(issues) == 0

    # --- ContentSanitizer ---

    def test_sanitize_removes_ai_noise(self):
        from web.documents.file_quality_checker import ContentSanitizer

        result = ContentSanitizer.sanitize_text("当然可以！这是内容")
        assert "当然可以" not in result
        assert "内容" in result

    def test_sanitize_removes_ai_dialogue(self):
        from web.documents.file_quality_checker import ContentSanitizer

        result = ContentSanitizer.sanitize_text("数据分析报告 希望这对你有帮助")
        assert "希望这对你有帮助" not in result

    def test_sanitize_preserves_normal_text(self):
        from web.documents.file_quality_checker import ContentSanitizer

        text = "这是一段正常的技术文档内容"
        assert ContentSanitizer.sanitize_text(text) == text

    def test_sanitize_ppt_outline(self):
        from web.documents.file_quality_checker import ContentSanitizer

        outline = [
            {"title": "**第一章**", "points": ["当然可以！要点一", "要点二"]},
            {"title": "第二章", "content": ["内容A"]},
        ]
        cleaned, fixes = ContentSanitizer.sanitize_ppt_outline(outline)
        assert len(fixes) > 0
        # Bold markers should be removed from title
        assert "**" not in cleaned[0]["title"]

    def test_sanitize_document_text(self):
        from web.documents.file_quality_checker import ContentSanitizer

        text = "当然可以！以下是报告内容：\n第一段正文\n希望这对你有帮助"
        cleaned, fixes = ContentSanitizer.sanitize_document_text(text)
        assert len(fixes) > 0

    # --- FileQualityEvaluator ---

    def test_evaluate_ppt_outline_good(self):
        from web.documents.file_quality_checker import FileQualityEvaluator

        outline = [
            {
                "title": "引言",
                "type": "detail",
                "points": ["要点A长度足够了", "要点B长度足够了", "要点C长度足够了"],
            },
            {
                "title": "方法论",
                "type": "detail",
                "points": [
                    "研究方法一详细描述",
                    "研究方法二详细描述",
                    "研究方法三详细描述",
                ],
            },
            {
                "title": "结果与分析",
                "type": "detail",
                "points": [
                    "结果一的详细内容描述",
                    "结果二的详细内容描述",
                    "结果三的详细内容描述",
                ],
            },
            {
                "title": "结论总结",
                "type": "detail",
                "points": [
                    "总结要点一详细内容",
                    "总结要点二详细内容",
                    "总结要点三详细内容",
                ],
            },
        ]
        result = FileQualityEvaluator.evaluate_ppt_outline(outline)
        assert result["pass"] is True
        assert result["score"] >= 60

    def test_evaluate_ppt_outline_empty(self):
        from web.documents.file_quality_checker import FileQualityEvaluator

        result = FileQualityEvaluator.evaluate_ppt_outline([])
        assert result["score"] < 100
        assert "过少" in str(result["issues"])

    def test_evaluate_document_text_good(self):
        from web.documents.file_quality_checker import FileQualityEvaluator

        text = (
            "# 报告标题\n\n"
            + "这是一段很长的正文内容。" * 50
            + "\n\n## 小节\n\n更多内容在这里。"
        )
        result = FileQualityEvaluator.evaluate_document_text(text)
        assert result["pass"] is True

    def test_evaluate_document_text_empty(self):
        from web.documents.file_quality_checker import FileQualityEvaluator

        result = FileQualityEvaluator.evaluate_document_text("")
        assert result["score"] == 0
        assert result["pass"] is False

    # --- FileQualityGate ---

    def test_gate_check_ppt_outline_proceed(self):
        from web.documents.file_quality_checker import FileQualityGate

        outline = [
            {
                "title": "标题页面",
                "type": "detail",
                "points": ["详细要点一内容", "详细要点二内容", "详细要点三内容"],
            },
            {
                "title": "内容页面",
                "type": "detail",
                "points": ["详细要点一内容", "详细要点二内容", "详细要点三内容"],
            },
            {
                "title": "分析结果",
                "type": "detail",
                "points": ["详细要点一内容", "详细要点二内容", "详细要点三内容"],
            },
            {
                "title": "总结页面",
                "type": "detail",
                "points": ["详细要点一内容", "详细要点二内容", "详细要点三内容"],
            },
        ]
        result = FileQualityGate.check_and_fix_ppt_outline(outline)
        assert result["action"] in ("proceed", "warn")
        assert "outline" in result
        assert "quality" in result

    def test_gate_check_document_empty(self):
        from web.documents.file_quality_checker import FileQualityGate

        result = FileQualityGate.check_and_fix_document("")
        assert result["action"] == "regenerate"

    def test_gate_check_and_fix_for_export_empty(self):
        from web.documents.file_quality_checker import FileQualityGate

        result = FileQualityGate.check_and_fix_for_export("")
        assert result["stripped_md"] is False
        assert result["quality"]["score"] == 0

    def test_gate_check_and_fix_for_export_excel(self):
        from web.documents.file_quality_checker import FileQualityGate

        text = "# 标题\n\n" + "正文内容很长的段落。" * 50 + "\n\n**加粗文字**"
        result = FileQualityGate.check_and_fix_for_export(text, target_format="excel")
        assert "**" not in result["text"]
        assert "#" not in result["text"]


# ═══════════════════════════════════════════════════════════════════════════════
# SearchEngine
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSearchEngine:
    """Tests for app.core.services.search_engine.SearchEngine."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path
        self.workspace = str(tmp_path / "workspace")
        self.chats = str(tmp_path / "chats")
        os.makedirs(self.workspace, exist_ok=True)
        os.makedirs(self.chats, exist_ok=True)

    def _make_engine(self):
        from app.core.services.search_engine import SearchEngine

        engine = SearchEngine()
        engine.workspace_root = self.workspace
        engine.chats_root = self.chats
        engine.project_root = str(self.tmp_path)
        return engine

    def test_init_sets_paths(self):
        from app.core.services.search_engine import SearchEngine

        engine = SearchEngine()
        assert engine.workspace_root is not None
        assert engine.chats_root is not None

    def test_search_files_by_filename(self):
        engine = self._make_engine()
        # Create a file
        with open(os.path.join(self.workspace, "report.txt"), "w") as f:
            f.write("some content")
        results = engine.search_files("report")
        assert len(results) >= 1
        assert results[0]["type"] == "filename"

    def test_search_files_by_content(self):
        engine = self._make_engine()
        with open(os.path.join(self.workspace, "data.txt"), "w") as f:
            f.write("line1\nthe quick brown fox\nline3")
        results = engine.search_files("quick brown")
        assert len(results) >= 1
        assert results[0]["type"] == "content"
        assert results[0]["line"] == 2

    def test_search_files_no_match(self):
        engine = self._make_engine()
        results = engine.search_files("zzzznonexistentzzzz")
        assert len(results) == 0

    def test_search_chats(self):
        engine = self._make_engine()
        chat_data = {
            "messages": [
                {
                    "content": "Hello world",
                    "role": "user",
                    "timestamp": "2024-01-01T10:00:00",
                },
                {
                    "content": "Hi there",
                    "role": "assistant",
                    "timestamp": "2024-01-01T10:00:01",
                },
            ]
        }
        with open(os.path.join(self.chats, "chat1.json"), "w") as f:
            json.dump(chat_data, f)
        results = engine.search_chats("Hello")
        assert len(results) >= 1
        assert results[0]["type"] == "chat"
        assert results[0]["role"] == "user"

    def test_search_chats_no_chats_dir(self):
        engine = self._make_engine()
        engine.chats_root = "/nonexistent/path"
        results = engine.search_chats("test")
        assert results == []

    def test_search_notes_with_index(self):
        engine = self._make_engine()
        notes_dir = os.path.join(self.workspace, "notes")
        os.makedirs(notes_dir, exist_ok=True)
        index = {
            "note1": {
                "title": "Python Tips",
                "content": "Use list comprehensions for efficiency",
                "tags": ["python", "tips"],
                "category": "programming",
                "created_at": "2024-01-01T10:00:00",
            }
        }
        with open(os.path.join(notes_dir, "notes_index.json"), "w") as f:
            json.dump(index, f)
        results = engine.search_notes("Python")
        assert len(results) >= 1
        assert results[0]["type"] == "note"

    def test_search_notes_no_dir(self):
        engine = self._make_engine()
        results = engine.search_notes("anything")
        # Notes dir doesn't contain notes_index.json by default (no notes subdir)
        assert isinstance(results, list)

    def test_search_clipboard(self):
        engine = self._make_engine()
        clip_dir = os.path.join(self.workspace, "clipboard")
        os.makedirs(clip_dir, exist_ok=True)
        history = [
            {
                "content": "clipboard item one",
                "type": "text",
                "timestamp": "2024-06-01T10:00:00",
            },
            {
                "content": "another clipboard item",
                "type": "text",
                "timestamp": "2024-06-01T11:00:00",
            },
        ]
        with open(os.path.join(clip_dir, "history.json"), "w") as f:
            json.dump(history, f)
        results = engine.search_clipboard("clipboard item")
        assert len(results) >= 1

    def test_search_all_aggregates(self):
        engine = self._make_engine()
        results = engine.search_all("test")
        assert "files" in results
        assert "chats" in results
        assert "notes" in results
        assert "clipboard" in results

    def test_extract_match_context_found(self):
        engine = self._make_engine()
        ctx = engine._extract_match_context(
            "The quick brown fox jumps over the lazy dog", "fox", 20
        )
        assert "fox" in ctx

    def test_extract_match_context_not_found(self):
        engine = self._make_engine()
        ctx = engine._extract_match_context("Hello world", "zzz", 20)
        # Falls back to first N chars
        assert "Hello" in ctx

    def test_search_by_date_range_empty(self):
        engine = self._make_engine()
        results = engine.search_by_date_range("2024-01-01", "2024-01-31")
        assert isinstance(results, dict)

    def test_search_by_date_range_invalid_date(self):
        engine = self._make_engine()
        results = engine.search_by_date_range("not-a-date", "also-bad")
        assert isinstance(results, dict)

    def test_filter_by_date_iso(self):
        engine = self._make_engine()
        items = [
            {"timestamp": "2024-06-15T10:00:00"},
            {"timestamp": "2024-07-01T10:00:00"},
        ]
        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 30)
        filtered = engine._filter_by_date(items, start, end)
        assert len(filtered) == 1

    def test_get_search_engine_singleton(self):
        import app.core.services.search_engine as mod

        old = mod._search_engine
        mod._search_engine = None
        try:
            e1 = mod.get_search_engine()
            e2 = mod.get_search_engine()
            assert e1 is e2
        finally:
            mod._search_engine = old
