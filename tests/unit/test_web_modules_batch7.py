"""
Unit tests for web modules batch 7:
  PPTResourceManager, PPTContentPlanner, PPTLayoutPlanner, PPTImageMatcher,
  PPTMasterOrchestrator, PPTGenerationTaskHandler,
  task_dispatcher (TaskExecutor, DispatcherScheduler),
  ReminderManager, SmartFeedback,
  SuggestionEngine and TemplateLibrary.

Covers constructors, key public methods, and error handling with mocked I/O.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest


def run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# PPT Master — dataclasses and enums
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPPTMasterDataclasses:
    """Tests for SlideBlueprint, PPTBlueprint, and enums."""

    def test_slide_type_enum(self):
        from app.core.services.ppt_master import SlideType

        assert SlideType.TITLE.value == "title"
        assert SlideType.CONTENT_IMAGE.value == "content_image"

    def test_content_density_enum(self):
        from app.core.services.ppt_master import ContentDensity

        assert ContentDensity.LIGHT.value == "light"
        assert ContentDensity.DENSE.value == "dense"

    def test_slide_blueprint_to_dict(self):
        from app.core.services.ppt_master import (
            ContentDensity,
            SlideBlueprint,
            SlideType,
        )

        sb = SlideBlueprint(
            slide_index=0,
            slide_type=SlideType.TITLE,
            title="Test",
            content=["A", "B"],
        )
        d = sb.to_dict()
        assert d["slide_index"] == 0
        assert d["slide_type"] == "title"
        assert d["title"] == "Test"
        assert d["content"] == ["A", "B"]
        assert d["density"] == "medium"

    def test_ppt_blueprint_to_dict(self):
        from app.core.services.ppt_master import PPTBlueprint

        bp = PPTBlueprint(title="My PPT", subtitle="sub")
        d = bp.to_dict()
        assert d["title"] == "My PPT"
        assert d["subtitle"] == "sub"
        assert d["slides"] == []

    def test_ppt_blueprint_add_log(self):
        from app.core.services.ppt_master import PPTBlueprint

        bp = PPTBlueprint(title="T", subtitle="S")
        bp.add_log("test message")
        assert len(bp.generation_log) == 1
        assert "test message" in bp.generation_log[0]


# ═══════════════════════════════════════════════════════════════════════════════
# PPT Master — ResourceManager
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPPTResourceManager:
    """Tests for app.core.services.ppt_master.PPTResourceManager."""

    def _make_rm(self):
        from app.core.services.ppt_master import PPTResourceManager

        return PPTResourceManager()

    def test_init(self):
        rm = self._make_rm()
        assert rm.search_results == {}
        assert rm.images == {}

    def test_add_search_results(self):
        rm = self._make_rm()
        results = [{"title": "T1", "url": "http://x", "content": "abc"}]
        rm.add_search_results("ai", results)
        assert "ai" in rm.search_results
        assert len(rm.references) == 1

    def test_add_images(self):
        rm = self._make_rm()
        rm.add_images("tech", ["/img1.png", "/img2.png"])
        assert rm.images["tech"] == ["/img1.png", "/img2.png"]
        assert len(rm.generated_images) == 2

    def test_get_best_images(self):
        rm = self._make_rm()
        rm.add_images("tech", ["/a.png", "/b.png", "/c.png"])
        assert len(rm.get_best_images("tech", 2)) == 2

    def test_get_best_images_missing_keyword(self):
        rm = self._make_rm()
        assert rm.get_best_images("nonexistent") == []

    def test_get_summary_for_blueprint(self):
        rm = self._make_rm()
        rm.add_search_results("k", [{"title": "", "url": "", "content": "x"}])
        rm.add_images("k", ["/img.png"])
        summary = rm.get_summary_for_blueprint()
        assert summary["search_keywords_count"] == 1
        assert summary["generated_images_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# PPT Master — LayoutPlanner
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPPTLayoutPlanner:
    """Tests for app.core.services.ppt_master.PPTLayoutPlanner."""

    def _make_planner(self):
        from app.core.services.ppt_master import PPTLayoutPlanner

        return PPTLayoutPlanner()

    def test_init(self):
        planner = self._make_planner()
        assert "title_heavy" in planner.layout_rules
        assert "balanced" in planner.layout_rules

    def test_plan_layout_title(self):
        from app.core.services.ppt_master import (
            PPTLayoutPlanner,
            SlideBlueprint,
            SlideType,
        )

        planner = PPTLayoutPlanner()
        sb = SlideBlueprint(slide_index=0, slide_type=SlideType.TITLE, title="T")
        config = planner.plan_layout(sb)
        assert config["title_size"] == 54

    def test_plan_layout_comparison(self):
        from app.core.services.ppt_master import (
            PPTLayoutPlanner,
            SlideBlueprint,
            SlideType,
        )

        planner = PPTLayoutPlanner()
        sb = SlideBlueprint(slide_index=1, slide_type=SlideType.COMPARISON, title="C")
        config = planner.plan_layout(sb)
        assert "left_width" in config

    def test_plan_layout_dense_content(self):
        from app.core.services.ppt_master import (
            ContentDensity,
            PPTLayoutPlanner,
            SlideBlueprint,
            SlideType,
        )

        planner = PPTLayoutPlanner()
        sb = SlideBlueprint(
            slide_index=2,
            slide_type=SlideType.CONTENT,
            title="D",
            density=ContentDensity.DENSE,
        )
        config = planner.plan_layout(sb, content_count=6)
        assert config.get("line_spacing") == 1.3

    def test_optimize_slide_count(self):
        planner = self._make_planner()
        assert planner.optimize_slide_count(3) == 5
        assert planner.optimize_slide_count(20) == 15
        assert planner.optimize_slide_count(10) == 10

    def test_choose_bullet_style(self):
        from app.core.services.ppt_master import PPTLayoutPlanner, SlideType

        planner = PPTLayoutPlanner()
        assert planner._choose_bullet_style(SlideType.TITLE) == "none"
        assert planner._choose_bullet_style(SlideType.CONTENT) == "circle"
        assert planner._choose_bullet_style(SlideType.SUMMARY) == "checkmark"


# ═══════════════════════════════════════════════════════════════════════════════
# PPT Master — ContentPlanner (default plan)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPPTContentPlanner:
    """Tests for app.core.services.ppt_master.PPTContentPlanner default plan generation."""

    def _make_planner(self):
        from app.core.services.ppt_master import PPTContentPlanner

        return PPTContentPlanner(ai_client=None)

    def test_init_no_client(self):
        planner = self._make_planner()
        assert planner.ai_client is None
        assert planner.model_name == "deepseek-chat"

    def test_generate_default_plan(self):
        planner = self._make_planner()
        plan = planner._generate_default_plan("关于AI的演示")
        assert "outline" in plan
        assert len(plan["outline"]) > 0
        assert plan["theme_recommendation"] == "business"

    def test_generate_default_plan_has_sections(self):
        planner = self._make_planner()
        plan = planner._generate_default_plan("关于量子计算的报告")
        sections = [s["section_title"] for s in plan["outline"]]
        assert "概述" in sections
        assert "总结" in sections

    def test_plan_content_structure_no_client(self):
        planner = self._make_planner()
        result = run_async(planner.plan_content_structure("关于Python的PPT"))
        assert "outline" in result

    def test_expand_slide_content_no_client(self):
        planner = self._make_planner()
        result = run_async(planner.expand_slide_content("Test", ["a", "b"]))
        assert result == ["a", "b"]


# ═══════════════════════════════════════════════════════════════════════════════
# PPT Master — ImageMatcher
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestPPTImageMatcher:
    """Tests for app.core.services.ppt_master.PPTImageMatcher."""

    def test_init(self):
        from app.core.services.ppt_master import PPTImageMatcher

        m = PPTImageMatcher(ai_client=None)
        assert m.image_cache == {}

    def test_generate_prompts_for_content_image(self):
        from app.core.services.ppt_master import (
            PPTImageMatcher,
            SlideBlueprint,
            SlideType,
        )

        m = PPTImageMatcher()
        prompts = m._generate_image_prompts_for_slide(
            SlideBlueprint(
                slide_index=0, slide_type=SlideType.CONTENT_IMAGE, title="AI Tech"
            ),
            "modern",
        )
        assert len(prompts) == 1
        assert "AI Tech" in prompts[0]

    def test_generate_prompts_for_comparison(self):
        from app.core.services.ppt_master import (
            PPTImageMatcher,
            SlideBlueprint,
            SlideType,
        )

        m = PPTImageMatcher()
        prompts = m._generate_image_prompts_for_slide(
            SlideBlueprint(
                slide_index=0, slide_type=SlideType.COMPARISON, title="A vs B"
            ),
            "flat",
        )
        assert len(prompts) == 2

    def test_generate_prompts_for_content_returns_empty(self):
        from app.core.services.ppt_master import (
            PPTImageMatcher,
            SlideBlueprint,
            SlideType,
        )

        m = PPTImageMatcher()
        prompts = m._generate_image_prompts_for_slide(
            SlideBlueprint(
                slide_index=0, slide_type=SlideType.CONTENT, title="Text only"
            ),
            "corporate",
        )
        assert prompts == []

    def test_generate_image_prompts_updates_slides(self):
        from app.core.services.ppt_master import (
            PPTImageMatcher,
            SlideBlueprint,
            SlideType,
        )

        m = PPTImageMatcher()
        slides = [
            SlideBlueprint(
                slide_index=0, slide_type=SlideType.CONTENT_IMAGE, title="Slide1"
            ),
            SlideBlueprint(slide_index=1, slide_type=SlideType.CONTENT, title="Slide2"),
        ]
        result = run_async(m.generate_image_prompts(slides, "pro"))
        assert len(result[0].image_prompts) > 0
        assert len(result[1].image_prompts) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Task Dispatcher (task_dispatcher.py)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.unit
@pytest.mark.unit
class TestReminderManager:
    """Tests for app.core.services.reminder_manager.ReminderManager."""

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_init(self, mock_exists, mock_makedirs, mock_toast):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        assert mgr.reminders == {}
        assert mgr.timers == {}

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_add_reminder(self, mock_exists, mock_makedirs, mock_toast):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        future = datetime.now() + timedelta(hours=1)
        with patch.object(mgr, "_save"):
            rid = mgr.add_reminder("Test", "Message", future)
            assert rid.startswith("reminder_")
            assert rid in mgr.reminders
            assert mgr.reminders[rid]["status"] == "scheduled"

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_add_reminder_in(self, mock_exists, mock_makedirs, mock_toast):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        with patch.object(mgr, "_save"):
            rid = mgr.add_reminder_in("Test", "Msg", 3600)
            assert rid in mgr.reminders

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    @patch("app.core.services.reminder_manager.threading.Timer")
    def test_far_future_reminder_defers_timer_registration(
        self, mock_timer, mock_exists, mock_makedirs, mock_toast
    ):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        with patch.object(mgr, "_save"):
            reminder_id = mgr.add_reminder(
                "Future", "Message", datetime.now() + timedelta(days=365 * 100)
            )

        assert reminder_id in mgr.reminders
        mock_timer.assert_not_called()

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_cancel_reminder(self, mock_exists, mock_makedirs, mock_toast):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        with patch.object(mgr, "_save"):
            rid = mgr.add_reminder("T", "M", datetime.now() + timedelta(hours=1))
            assert mgr.cancel_reminder(rid) is True
            assert mgr.reminders[rid]["status"] == "cancelled"
            assert mgr.cancel_reminder("nonexistent") is False

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_list_reminders(self, mock_exists, mock_makedirs, mock_toast):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        with patch.object(mgr, "_save"):
            mgr.add_reminder("A", "M", datetime.now() + timedelta(hours=1))
            mgr.add_reminder("B", "M", datetime.now() + timedelta(hours=2))
            assert len(mgr.list_reminders()) == 2

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_clear_expired(self, mock_exists, mock_makedirs, mock_toast):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        mgr.reminders = {
            "r1": {"status": "sent"},
            "r2": {"status": "expired"},
            "r3": {"status": "scheduled"},
        }
        with patch.object(mgr, "_save"):
            cleared = mgr.clear_expired()
            assert cleared == 2
            assert "r3" in mgr.reminders

    @patch("app.core.services.reminder_manager.show_toast")
    @patch("app.core.services.reminder_manager.os.makedirs")
    @patch("app.core.services.reminder_manager.os.path.exists", return_value=False)
    def test_restore_pending_marks_expired(
        self, mock_exists, mock_makedirs, mock_toast
    ):
        from app.core.services.reminder_manager import ReminderManager

        mgr = ReminderManager()
        old_time = (datetime.now() - timedelta(hours=2)).isoformat()
        mgr.reminders = {"r1": {"status": "pending", "time": old_time}}
        with patch.object(mgr, "_save"):
            mgr._restore_pending()
            assert mgr.reminders["r1"]["status"] == "expired"


# ═══════════════════════════════════════════════════════════════════════════════
# Smart Feedback
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSmartFeedback:
    """Tests for web.proactive.smart_feedback.SmartFeedback."""

    def _make_fb(self, **kwargs):
        from web.proactive.smart_feedback import SmartFeedback

        defaults = {
            "user_request": "帮我做一个关于AI的PPT",
            "task_type": "PPT",
            "emit": MagicMock(),
            "total_steps": 5,
        }
        defaults.update(kwargs)
        return SmartFeedback(**defaults)

    def test_init(self):
        fb = self._make_fb()
        assert fb.task_type == "PPT"
        assert fb.current_step == 0
        assert fb.total_steps == 5

    def test_extract_topic(self):
        fb = self._make_fb(user_request="帮我做一个关于量子计算的PPT")
        assert "量子计算" in fb._topic

    def test_start(self):
        fb = self._make_fb()
        msg, detail = fb.start()
        assert "开始" in msg or "制作" in msg
        fb.emit.assert_called_once()

    def test_step_with_total(self):
        fb = self._make_fb(total_steps=3)
        msg, _ = fb.step("Processing data")
        assert "[1/3]" in msg
        assert fb.current_step == 1

    def test_substep(self):
        fb = self._make_fb()
        msg, _ = fb.substep("Sub operation")
        assert "→" in msg

    def test_info(self):
        fb = self._make_fb()
        msg, _ = fb.info("Information message")
        assert msg == "Information message"

    def test_warn(self):
        fb = self._make_fb()
        msg, _ = fb.warn("Warning!")
        assert "⚠️" in msg

    def test_done(self):
        fb = self._make_fb()
        msg, _ = fb.done("All complete")
        assert "✅" in msg
        assert "耗时" in msg

    def test_error(self):
        fb = self._make_fb()
        msg, _ = fb.error("Something broke")
        assert "❌" in msg

    def test_quality_report_excellent(self):
        fb = self._make_fb()
        msg, _ = fb.quality_report(90)
        assert "✅" in msg

    def test_quality_report_poor(self):
        fb = self._make_fb()
        msg, _ = fb.quality_report(50, issues=["issue1"], fixes=["fix1"])
        assert "⚠️" in msg

    def test_ppt_planning(self):
        fb = self._make_fb()
        msg, _ = fb.ppt_planning("some context")
        assert "规划" in msg

    def test_ppt_outline_ready(self):
        fb = self._make_fb()
        msg, _ = fb.ppt_outline_ready(10, title="Test PPT")
        assert "10" in msg

    def test_ppt_enriching(self):
        fb = self._make_fb()
        msg, _ = fb.ppt_enriching(5)
        assert "5" in msg

    def test_for_ppt_factory(self):
        from web.proactive.smart_feedback import SmartFeedback

        fb = SmartFeedback.for_ppt("request", MagicMock())
        assert fb.task_type == "PPT"
        assert fb.total_steps == 7

    def test_for_document_factory(self):
        from web.proactive.smart_feedback import SmartFeedback

        fb = SmartFeedback.for_document("request", MagicMock(), "EXCEL")
        assert fb.task_type == "EXCEL"

    def test_heartbeat_start_stop(self):
        fb = self._make_fb()
        fb.start_heartbeat(interval=100)
        assert fb._heartbeat_active is True
        fb.stop_heartbeat()
        assert fb._heartbeat_active is False


# ═══════════════════════════════════════════════════════════════════════════════
# Suggestion Engine
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestSuggestionEngine:
    """Tests for web.proactive.suggestion_engine.SuggestionEngine."""

    @pytest.fixture(autouse=True)
    def _patch_imports(self):
        """Ensure suggestion_engine can be imported by mocking its dependencies."""
        mock_bm_mod = MagicMock()
        mock_kg_mod = MagicMock()
        # Set up the EVENT_FILE_CREATE and EVENT_FILE_OPEN constants
        mock_bm_mod.BehaviorMonitor.EVENT_FILE_CREATE = "file_create"
        mock_bm_mod.BehaviorMonitor.EVENT_FILE_OPEN = "file_open"

        patches = {}
        modules_to_mock = [
            "web.behavior_monitor",
            "behavior_monitor",
            "web.knowledge.knowledge_graph",
            "knowledge_graph",
            "concept_extractor",
        ]
        import sys

        for mod_name in modules_to_mock:
            if mod_name in ("web.behavior_monitor", "behavior_monitor"):
                patches[mod_name] = mock_bm_mod
            elif mod_name in ("web.knowledge.knowledge_graph", "knowledge_graph"):
                patches[mod_name] = mock_kg_mod
            else:
                patches[mod_name] = MagicMock()

        # Remove cached module if it failed earlier
        for key in list(sys.modules.keys()):
            if "suggestion_engine" in key:
                del sys.modules[key]

        with patch.dict("sys.modules", patches):
            # Re-import with mocked deps
            import importlib

            if "web.proactive.suggestion_engine" in sys.modules:
                importlib.reload(sys.modules["web.proactive.suggestion_engine"])
            yield

    def _make_engine(self, db_path=":memory:"):
        from web.proactive.suggestion_engine import SuggestionEngine

        mock_bm = MagicMock()
        mock_kg = MagicMock()
        # Set constants on the mock
        mock_bm.EVENT_FILE_CREATE = "file_create"
        mock_bm.EVENT_FILE_OPEN = "file_open"
        engine = SuggestionEngine(
            behavior_monitor=mock_bm,
            knowledge_graph=mock_kg,
            db_path=db_path,
        )
        return engine, mock_bm, mock_kg

    def test_init(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, _, _ = self._make_engine(db_path=db)
        assert len(engine.rules) == 8

    def test_save_and_get_pending(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, _, _ = self._make_engine(db_path=db)
        suggestion = {
            "type": "organize",
            "title": "Test",
            "description": "Desc",
            "priority": "medium",
            "context": {},
            "action_items": [],
        }
        sid = engine._save_suggestion(suggestion)
        assert sid > 0
        pending = engine.get_pending_suggestions()
        assert len(pending) == 1
        assert pending[0]["title"] == "Test"

    def test_dismiss_suggestion(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, _, _ = self._make_engine(db_path=db)
        sid = engine._save_suggestion(
            {
                "type": "backup",
                "title": "T",
                "description": "D",
                "priority": "low",
                "context": {},
                "action_items": [],
            }
        )
        engine.dismiss_suggestion(sid, "not useful")
        pending = engine.get_pending_suggestions()
        assert len(pending) == 0

    def test_apply_suggestion(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, _, _ = self._make_engine(db_path=db)
        sid = engine._save_suggestion(
            {
                "type": "cleanup",
                "title": "T",
                "description": "D",
                "priority": "high",
                "context": {},
                "action_items": [],
            }
        )
        engine.apply_suggestion(sid)
        pending = engine.get_pending_suggestions()
        assert len(pending) == 0

    def test_get_statistics(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, _, _ = self._make_engine(db_path=db)
        engine._save_suggestion(
            {
                "type": "optimize",
                "title": "T",
                "description": "D",
                "priority": "low",
                "context": {},
                "action_items": [],
            }
        )
        stats = engine.get_statistics()
        assert stats["total_suggestions"] == 1
        assert stats["pending_suggestions"] == 1

    def test_rule_repeated_file_pattern_no_events(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, mock_bm, _ = self._make_engine(db_path=db)
        mock_bm.get_recent_events.return_value = []
        result = engine._rule_repeated_file_pattern()
        assert result == []

    def test_rule_repeated_file_pattern_with_events(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, mock_bm, _ = self._make_engine(db_path=db)
        events = [{"file_path": f"/doc/file{i}.docx"} for i in range(6)]
        mock_bm.get_recent_events.return_value = events
        result = engine._rule_repeated_file_pattern()
        assert len(result) >= 1
        assert result[0]["type"] == "workflow"

    def test_log_rule_execution(self, tmp_path):
        db = str(tmp_path / "test.db")
        engine, _, _ = self._make_engine(db_path=db)
        engine._log_rule_execution("test_rule", True, 3)
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT * FROM rule_history").fetchall()
        conn.close()
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Suggestion Annotator
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.unit
class TestTemplateLibrary:
    """Tests for web.tasks.template_library.TemplateLibrary."""

    @patch("web.tasks.template_library.os.makedirs")
    def _make_library(self, mock_makedirs, workspace_dir="/tmp/ws"):
        from web.tasks.template_library import TemplateLibrary

        return TemplateLibrary(workspace_dir=workspace_dir)

    def test_init(self):
        lib = self._make_library()
        assert lib.workspace_dir == "/tmp/ws"

    def test_list_templates(self):
        lib = self._make_library()
        templates = lib.list_templates()
        assert len(templates) >= 8
        ids = [t["id"] for t in templates]
        assert "business_report" in ids
        assert "resume_modern" in ids

    def test_get_template_exists(self):
        lib = self._make_library()
        t = lib.get_template("business_report")
        assert t is not None
        assert t["name"] == "商业报告"

    def test_get_template_not_found(self):
        lib = self._make_library()
        assert lib.get_template("nonexistent") is None

    def test_generate_from_template_not_found(self):
        lib = self._make_library()
        result = lib.generate_from_template("nonexistent", {})
        assert result["success"] is False

    def test_generate_from_template_unsupported_type(self):
        lib = self._make_library()
        # Temporarily add a bad template
        lib.TEMPLATES["bad"] = {
            "name": "Bad",
            "type": "xyz",
            "description": "",
            "variables": [],
        }
        result = lib.generate_from_template("bad", {})
        assert result["success"] is False
        del lib.TEMPLATES["bad"]

    @patch("web.tasks.template_library.os.makedirs")
    def test_build_business_report(self, mock_makedirs):
        lib = self._make_library()
        content = lib._build_business_report(
            {
                "title": "Test Report",
                "author": "Tester",
                "company": "Corp",
                "executive_summary": "Summary",
                "main_content": "Content",
                "conclusion": "Done",
            }
        )
        assert "Test Report" in content
        assert "Tester" in content

    @patch("web.tasks.template_library.os.makedirs")
    def test_build_resume(self, mock_makedirs):
        lib = self._make_library()
        content = lib._build_resume({"name": "John", "email": "j@x.com"})
        assert "John" in content

    @patch("web.tasks.template_library.os.makedirs")
    def test_build_product_ppt_outline(self, mock_makedirs):
        lib = self._make_library()
        outline = lib._build_product_ppt_outline(
            {
                "product_name": "Widget",
                "tagline": "Better widgets",
                "features": "Fast\nReliable",
            }
        )
        assert len(outline) == 6
        assert outline[0]["title"] == "产品概览"

    @patch("web.tasks.template_library.PPTGenerationService")
    @patch("web.tasks.template_library.os.makedirs")
    def test_generate_ppt_template_uses_generation_service(
        self, mock_makedirs, mock_service_cls
    ):
        from web.tasks.template_library import TemplateLibrary

        mock_service = mock_service_cls.return_value
        mock_service.generate_outline_result.return_value = {
            "success": True,
            "output_path": "/tmp/out/Widget.pptx",
            "slide_count": 6,
        }
        lib = TemplateLibrary(workspace_dir="/tmp/ws")

        result = lib._generate_pptx_from_template(
            "product_intro_ppt",
            {"name": "产品介绍"},
            {
                "product_name": "Widget",
                "tagline": "Better widgets",
                "speaker": "Tester",
            },
            "/tmp/out",
        )

        call_kwargs = mock_service.generate_outline_result.call_args.kwargs
        assert call_kwargs["title"] == "Widget"
        assert call_kwargs["theme"] == "business"
        assert call_kwargs["subtitle"] == "Better widgets"
        assert call_kwargs["author"] == "Tester"
        assert result["success"] is True
        assert result["slide_count"] == 6
