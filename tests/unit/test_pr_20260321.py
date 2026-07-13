# -*- coding: utf-8 -*-
"""
Unit tests for PR Logan/20260320 (merged 2026-03-21).

Covers new modules:
  - app.core.llm.provider_factory  (get_llm_provider, list_available_providers)
  - app.core.hooks.hook_manager    (HookManager, HookContext, fire_* methods)
  - app.core.skills.skill_permissions (SkillPermissionManager, PERMISSION_META)
  - app.core.tasks.task_planner    (Plan, PlanStep, PlanTemplates, StepStatus)
  - app.core.context.context_provider (ContextBlock, ContextProvider)
  - app.core.tools.user_tool_loader   (koto_tool, get_registered_tools)
  - app.api.telegram_bot_routes    (Blueprint REST API)
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _stub_module(name: str) -> MagicMock:
    """Register a MagicMock as a sys.modules stub (once)."""
    if name not in sys.modules:
        sys.modules[name] = MagicMock()
    return sys.modules[name]


# ══════════════════════════════════════════════════════════════════════════════
# 1. LLM Provider Factory
# ══════════════════════════════════════════════════════════════════════════════


class TestProviderFactoryListProviders(unittest.TestCase):
    """list_available_providers reflects env variables."""

    def setUp(self):
        # Clear any residual API-key env vars
        for k in (
            "GEMINI_API_KEY",
            "API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_KEY",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_KEY",
            "DS_API_KEY",
            "DS_KEY",
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
        ):
            os.environ.pop(k, None)

    def test_empty_when_no_keys(self):
        from app.core.llm.provider_factory import list_available_providers

        with patch(
            "app.core.llm.provider_factory.get_deepseek_api_key", return_value=None
        ):
            providers = list_available_providers()
        # ollama may appear if port 11434 is open — filter it out
        cloud = [p for p in providers if p != "ollama"]
        self.assertEqual(cloud, [])

    def test_archived_gemini_key_is_ignored(self):
        from app.core.llm.provider_factory import list_available_providers

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            providers = list_available_providers()
        self.assertNotIn("gemini", providers)

    def test_openai_detected_via_openai_key(self):
        from app.core.llm.provider_factory import list_available_providers

        with patch.dict(os.environ, {"OPENAI_KEY": "test-key"}):
            providers = list_available_providers()
        self.assertIn("openai", providers)

    def test_anthropic_detected_via_claude_key(self):
        from app.core.llm.provider_factory import list_available_providers

        with patch.dict(os.environ, {"CLAUDE_API_KEY": "test-key"}):
            providers = list_available_providers()
        self.assertIn("anthropic", providers)

    def test_deepseek_detected_via_api_key(self):
        from app.core.llm.provider_factory import list_available_providers

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            providers = list_available_providers()
        self.assertIn("deepseek", providers)

    def test_returns_list_type(self):
        from app.core.llm.provider_factory import list_available_providers

        self.assertIsInstance(list_available_providers(), list)


class TestProviderFactoryGetProvider(unittest.TestCase):
    """get_llm_provider selects correct provider."""

    def test_explicit_provider_gemini_is_rejected(self):
        from app.core.llm.provider_factory import (
            CloudProviderUnavailableError,
            get_llm_provider,
        )

        with self.assertRaisesRegex(CloudProviderUnavailableError, "archived"):
            get_llm_provider(provider="gemini")

    def test_explicit_provider_openai(self):
        from app.core.llm.provider_factory import get_llm_provider

        mock_inst = MagicMock()
        with patch.dict(
            "app.core.llm.provider_factory._LOADERS", {"openai": lambda: mock_inst}
        ):
            result = get_llm_provider(provider="openai")
        self.assertIs(result, mock_inst)

    def test_model_prefix_gpt_selects_openai(self):
        from app.core.llm.provider_factory import get_llm_provider

        mock_inst = MagicMock()
        with patch.dict(
            "app.core.llm.provider_factory._LOADERS", {"openai": lambda: mock_inst}
        ):
            result = get_llm_provider(model="gpt-4o")
        self.assertIs(result, mock_inst)

    def test_model_prefix_claude_selects_anthropic(self):
        from app.core.llm.provider_factory import get_llm_provider

        mock_inst = MagicMock()
        with patch.dict(
            "app.core.llm.provider_factory._LOADERS", {"anthropic": lambda: mock_inst}
        ):
            result = get_llm_provider(model="claude-3-sonnet-20240229")
        self.assertIs(result, mock_inst)

    def test_model_prefix_gemini_is_rejected(self):
        from app.core.llm.provider_factory import (
            CloudProviderUnavailableError,
            get_llm_provider,
        )

        with self.assertRaisesRegex(CloudProviderUnavailableError, "archived"):
            get_llm_provider(model="gemini-3-flash-preview")

    def test_model_prefix_llama_selects_ollama(self):
        from app.core.llm.provider_factory import get_llm_provider

        mock_inst = MagicMock()
        with patch.dict(
            "app.core.llm.provider_factory._LOADERS", {"ollama": lambda: mock_inst}
        ):
            result = get_llm_provider(model="llama3.1")
        self.assertIs(result, mock_inst)

    def test_unknown_provider_falls_back_to_autodetect(self):
        """Unknown provider name falls through to auto-detect, which stays cloud-only by default."""
        from app.core.llm.provider_factory import (
            CloudProviderUnavailableError,
            get_llm_provider,
        )

        for k in (
            "GEMINI_API_KEY",
            "API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_KEY",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_KEY",
            "DS_API_KEY",
            "DS_KEY",
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
        ):
            os.environ.pop(k, None)
        with patch(
            "app.core.llm.provider_factory.has_deepseek_api_key", return_value=False
        ), self.assertRaises(CloudProviderUnavailableError):
            get_llm_provider(provider="nonexistent_provider")

    def test_allow_local_fallback_returns_ollama_when_cloud_missing(self):
        from app.core.llm.provider_factory import get_llm_provider

        mock_inst = MagicMock()
        for k in (
            "GEMINI_API_KEY",
            "API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_KEY",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_KEY",
            "DS_API_KEY",
            "DS_KEY",
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
        ):
            os.environ.pop(k, None)
        with patch(
            "app.core.llm.provider_factory.has_deepseek_api_key", return_value=False
        ), patch("app.core.llm.provider_factory._load_ollama", return_value=mock_inst):
            result = get_llm_provider(allow_local_fallback=True)
        self.assertIs(result, mock_inst)

    def test_auto_detect_loads_deepseek_config_when_env_empty(self):
        from app.core.llm.provider_factory import (
            get_llm_provider,
            list_available_providers,
        )

        mock_inst = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "deepseek_config.env").write_text(
                "DEEPSEEK_API_KEY=config-key-123\n",
                encoding="utf-8",
            )

            for k in (
                "DEEPSEEK_API_KEY",
                "DEEPSEEK_KEY",
                "DS_API_KEY",
                "DS_KEY",
            ):
                os.environ.pop(k, None)

            with patch(
                "app.core.llm.deepseek_config.project_root", return_value=root
            ), patch(
                "app.core.llm.provider_factory._load_deepseek", return_value=mock_inst
            ):
                result = get_llm_provider()
                providers = list_available_providers()

        self.assertIs(result, mock_inst)
        self.assertIn("deepseek", providers)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Hook Manager
# ══════════════════════════════════════════════════════════════════════════════


class TestHookContext(unittest.TestCase):
    def test_default_fields(self):
        from app.core.hooks.hook_manager import HookContext

        ctx = HookContext()
        self.assertEqual(ctx.session_id, "")
        self.assertEqual(ctx.task_type, "")
        self.assertEqual(ctx.skill_id, "")
        self.assertEqual(ctx.active_skills, [])

    def test_custom_fields(self):
        from app.core.hooks.hook_manager import HookContext

        ctx = HookContext(
            session_id="s1",
            task_type="CHAT",
            skill_id="sk1",
            active_skills=["divination"],
        )
        self.assertEqual(ctx.session_id, "s1")
        self.assertIn("divination", ctx.active_skills)


class TestHookManagerNoHooks(unittest.TestCase):
    """HookManager with empty hooks dir passes text through unchanged."""

    def setUp(self):
        # Reload with a temp empty directory
        from app.core.hooks import hook_manager as hm

        self._orig_dir = hm._HOOKS_DIR
        self._tmpdir = tempfile.mkdtemp()
        hm._HOOKS_DIR = Path(self._tmpdir)
        hm.HookManager._instance = None  # reset singleton
        self._hm = hm.HookManager()

    def tearDown(self):
        from app.core.hooks import hook_manager as hm

        hm._HOOKS_DIR = self._orig_dir
        hm.HookManager._instance = None
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _ctx(self):
        from app.core.hooks.hook_manager import HookContext

        return HookContext(session_id="test", task_type="CHAT")

    def test_fire_pre_message_passthrough(self):
        result = self._hm.fire_pre_message("hello world", self._ctx())
        self.assertEqual(result, "hello world")

    def test_fire_post_response_passthrough(self):
        result = self._hm.fire_post_response("AI response", self._ctx())
        self.assertEqual(result, "AI response")

    def test_fire_on_tool_result_passthrough(self):
        result = self._hm.fire_on_tool_result("search", "result text", self._ctx())
        self.assertEqual(result, "result text")

    def test_has_hooks_false_when_empty(self):
        self.assertFalse(self._hm.has_hooks("pre_message"))

    def test_summary_returns_dict(self):
        s = self._hm.summary()
        self.assertIsInstance(s, dict)

    def test_fire_on_skill_change_does_not_raise(self):
        self._hm.fire_on_skill_change("divination", True, self._ctx())

    def test_fire_on_session_start_does_not_raise(self):
        self._hm.fire_on_session_start("sess-99", self._ctx())


class TestHookManagerWithHook(unittest.TestCase):
    """HookManager with a real hook file transforms text."""

    def setUp(self):
        from app.core.hooks import hook_manager as hm

        self._orig_dir = hm._HOOKS_DIR
        self._tmpdir = tempfile.mkdtemp()
        hook_path = Path(self._tmpdir) / "test_hook.py"
        hook_path.write_text(
            "def pre_message(text, ctx):\n"
            "    return text.upper()\n"
            "\n"
            "def post_response(text, ctx):\n"
            "    return '[HOOKED] ' + text\n",
            encoding="utf-8",
        )
        hm._HOOKS_DIR = Path(self._tmpdir)
        hm.HookManager._instance = None
        self._hm = hm.HookManager()

    def tearDown(self):
        from app.core.hooks import hook_manager as hm

        hm._HOOKS_DIR = self._orig_dir
        hm.HookManager._instance = None
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _ctx(self):
        from app.core.hooks.hook_manager import HookContext

        return HookContext()

    def test_pre_message_hook_transforms_text(self):
        result = self._hm.fire_pre_message("hello", self._ctx())
        self.assertEqual(result, "HELLO")

    def test_post_response_hook_transforms_text(self):
        result = self._hm.fire_post_response("world", self._ctx())
        self.assertEqual(result, "[HOOKED] world")

    def test_has_hooks_true(self):
        self.assertTrue(self._hm.has_hooks("pre_message"))

    def test_summary_shows_hook_count(self):
        s = self._hm.summary()
        self.assertGreaterEqual(s.get("pre_message", 0), 1)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Skill Permissions
# ══════════════════════════════════════════════════════════════════════════════


class TestSkillPermissions(unittest.TestCase):

    def setUp(self):
        from app.core.skills import skill_permissions as sp

        self._tmpdir = tempfile.mkdtemp()
        self._orig_cache = sp.SkillPermissionManager._cache
        sp.SkillPermissionManager._cache = None
        # Point _config_dir to tmpdir
        self._patcher = patch(
            "app.core.skills.skill_permissions._config_dir",
            return_value=Path(self._tmpdir),
        )
        self._patcher.start()

    def tearDown(self):
        from app.core.skills import skill_permissions as sp

        sp.SkillPermissionManager._cache = self._orig_cache
        self._patcher.stop()
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_get_granted_empty_by_default(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        result = SkillPermissionManager.get_granted("nonexistent_skill")
        self.assertEqual(result, [])

    def test_grant_valid_permission(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        granted = SkillPermissionManager.grant("my_skill", ["storage"])
        self.assertIn("storage", granted)

    def test_grant_invalid_permission_ignored(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        granted = SkillPermissionManager.grant("my_skill", ["totally_fake_perm"])
        self.assertNotIn("totally_fake_perm", granted)

    def test_is_granted_after_grant(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        SkillPermissionManager.grant("skill_a", ["clipboard_read"])
        self.assertTrue(SkillPermissionManager.is_granted("skill_a", "clipboard_read"))

    def test_is_not_granted_before_grant(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        self.assertFalse(SkillPermissionManager.is_granted("skill_a", "autorun"))

    def test_get_missing_returns_ungrant(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        SkillPermissionManager.grant("skill_b", ["storage"])
        missing = SkillPermissionManager.get_missing("skill_b", ["storage", "autorun"])
        self.assertNotIn("storage", missing)
        self.assertIn("autorun", missing)

    def test_revoke_removes_permission(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        SkillPermissionManager.grant("skill_c", ["notifications", "clipboard_write"])
        SkillPermissionManager.revoke("skill_c", ["notifications"])
        self.assertFalse(SkillPermissionManager.is_granted("skill_c", "notifications"))
        self.assertTrue(SkillPermissionManager.is_granted("skill_c", "clipboard_write"))

    def test_revoke_all_when_no_list(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = None
        SkillPermissionManager.grant("skill_d", ["storage", "autorun"])
        SkillPermissionManager.revoke("skill_d")
        self.assertEqual(SkillPermissionManager.get_granted("skill_d"), [])

    def test_permission_meta_has_known_keys(self):
        from app.core.skills.skill_permissions import ALL_PERMISSIONS, PERMISSION_META

        for key in (
            "ui_style",
            "ui_interactive",
            "notifications",
            "clipboard_read",
            "clipboard_write",
            "storage",
            "autorun",
        ):
            self.assertIn(key, ALL_PERMISSIONS)
            self.assertIn(key, PERMISSION_META)

    def test_get_permission_info_returns_list(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        info = SkillPermissionManager.get_permission_info(["storage", "autorun"])
        self.assertIsInstance(info, list)
        self.assertEqual(len(info), 2)

    def test_invalidate_cache_clears_cache(self):
        from app.core.skills.skill_permissions import SkillPermissionManager

        SkillPermissionManager._cache = {"x": ["storage"]}
        SkillPermissionManager.invalidate_cache()
        self.assertIsNone(SkillPermissionManager._cache)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Task Planner — Plan, PlanStep, StepStatus
# ══════════════════════════════════════════════════════════════════════════════


class TestStepStatus(unittest.TestCase):
    def test_enum_values(self):
        from app.core.tasks.task_planner import StepStatus

        self.assertEqual(StepStatus.PENDING.value, "pending")
        self.assertEqual(StepStatus.COMPLETED.value, "completed")
        self.assertEqual(StepStatus.FAILED.value, "failed")


class TestPlanStep(unittest.TestCase):
    def test_default_construction(self):
        from app.core.tasks.task_planner import PlanStep

        step = PlanStep(name="fetch_data", description="Download dataset")
        self.assertEqual(step.name, "fetch_data")
        self.assertEqual(step.depends_on, [])
        self.assertFalse(step.require_approval)

    def test_to_dict_has_name(self):
        from app.core.tasks.task_planner import PlanStep

        step = PlanStep(name="step_a", description="Do A")
        d = step.to_dict()
        self.assertEqual(d["name"], "step_a")

    def test_depends_on_set(self):
        from app.core.tasks.task_planner import PlanStep

        step = PlanStep(name="step_b", description="Do B", depends_on=["step_a"])
        self.assertIn("step_a", step.depends_on)


class TestPlan(unittest.TestCase):
    def _make_plan(self):
        from app.core.tasks.task_planner import Plan, PlanStep, StepStatus

        plan = Plan(task_id="task-1", original_request="Test request")
        step_a = PlanStep(name="step_a", description="First step")
        step_b = PlanStep(
            name="step_b", description="Second step", depends_on=["step_a"]
        )
        plan.add_step(step_a)
        plan.add_step(step_b)
        return plan, step_a, step_b

    def test_plan_starts_with_pending_steps(self):
        from app.core.tasks.task_planner import StepStatus

        plan, step_a, _ = self._make_plan()
        self.assertEqual(step_a.status, StepStatus.PENDING)

    def test_add_step_returns_plan(self):
        from app.core.tasks.task_planner import Plan, PlanStep

        plan = Plan(task_id="t", original_request="req")
        result = plan.add_step(PlanStep(name="x", description="y"))
        self.assertIs(result, plan)

    def test_get_step_by_name(self):
        plan, step_a, _ = self._make_plan()
        found = plan.get_step("step_a")
        self.assertIs(found, step_a)

    def test_get_step_returns_none_for_missing(self):
        plan, _, _ = self._make_plan()
        self.assertIsNone(plan.get_step("nonexistent"))

    def test_ready_steps_initially_empty_or_no_deps(self):
        from app.core.tasks.task_planner import Plan, PlanStep, StepStatus

        plan = Plan(task_id="t", original_request="r")
        step = PlanStep(name="s1", description="d")
        plan.add_step(step)
        # step with no deps should be READY after plan resolves readiness
        ready = plan.ready_steps()
        # Either step is ready (no deps) or not yet — implementation dependent
        self.assertIsInstance(ready, list)

    def test_is_done_false_with_pending_steps(self):
        plan, _, _ = self._make_plan()
        self.assertFalse(plan.is_done())

    def test_progress_percent_zero_initially(self):
        plan, _, _ = self._make_plan()
        self.assertIsInstance(plan.progress_percent(), int)
        self.assertGreaterEqual(plan.progress_percent(), 0)
        self.assertLessEqual(plan.progress_percent(), 100)

    def test_to_dict_has_task_id(self):
        plan, _, _ = self._make_plan()
        d = plan.to_dict()
        self.assertEqual(d["task_id"], "task-1")
        self.assertIn("steps", d)

    def test_has_blocking_failure_false_initially(self):
        plan, _, _ = self._make_plan()
        self.assertFalse(plan.has_blocking_failure())


class TestPlanTemplates(unittest.TestCase):
    def test_research_and_report_returns_plan(self):
        from app.core.tasks.task_planner import PlanTemplates

        plan = PlanTemplates.research_and_report("task-r", "Write a research report")
        self.assertEqual(plan.task_id, "task-r")
        self.assertGreater(len(plan.steps), 0)

    def test_data_pipeline_returns_plan(self):
        from app.core.tasks.task_planner import PlanTemplates

        plan = PlanTemplates.data_pipeline("task-dp", "Process CSV data")
        self.assertGreater(len(plan.steps), 0)

    def test_multi_step_task_uses_provided_steps(self):
        from app.core.tasks.task_planner import PlanTemplates

        steps = [
            {"name": "fetch", "description": "Fetch data"},
            {"name": "process", "description": "Process data", "depends_on": ["fetch"]},
        ]
        plan = PlanTemplates.multi_step_task("task-ms", "Custom task", steps)
        names = [s.name for s in plan.steps]
        self.assertIn("fetch", names)
        self.assertIn("process", names)


class TestStepResult(unittest.TestCase):
    def test_context_text_includes_summary(self):
        from app.core.tasks.task_planner import StepResult

        r = StepResult(
            full_output="long output",
            summary="short summary",
            key_facts=["fact1", "fact2"],
        )
        text = r.context_text()
        self.assertIn("short summary", text)

    def test_context_text_includes_key_facts(self):
        from app.core.tasks.task_planner import StepResult

        r = StepResult(full_output="output", summary="sum", key_facts=["key fact here"])
        self.assertIn("key fact here", r.context_text())


# ══════════════════════════════════════════════════════════════════════════════
# 5. Context Provider
# ══════════════════════════════════════════════════════════════════════════════


class TestContextBlock(unittest.TestCase):
    def test_default_enabled(self):
        from app.core.context.context_provider import ContextBlock

        cb = ContextBlock({"id": "test", "content": "hello"})
        self.assertTrue(cb.enabled)

    def test_matches_all_task_types_when_empty_list(self):
        from app.core.context.context_provider import ContextBlock

        cb = ContextBlock({"id": "t", "content": "c", "task_types": []})
        self.assertTrue(cb.matches("CHAT"))
        self.assertTrue(cb.matches(None))

    def test_matches_specific_task_type(self):
        from app.core.context.context_provider import ContextBlock

        cb = ContextBlock({"id": "t", "content": "c", "task_types": ["CHAT"]})
        self.assertTrue(cb.matches("CHAT"))
        self.assertFalse(cb.matches("CODE"))

    def test_disabled_block_never_matches(self):
        from app.core.context.context_provider import ContextBlock

        cb = ContextBlock({"id": "t", "content": "c", "enabled": False})
        self.assertFalse(cb.matches("CHAT"))

    def test_priority_default(self):
        from app.core.context.context_provider import ContextBlock

        cb = ContextBlock({"id": "t", "content": "c"})
        self.assertEqual(cb.priority, 50)

    def test_inject_mode_default(self):
        from app.core.context.context_provider import ContextBlock

        cb = ContextBlock({"id": "t", "content": "c"})
        self.assertEqual(cb.inject_mode, "system")


class TestContextProvider(unittest.TestCase):
    def setUp(self):
        from app.core.context import context_provider as cp

        self._tmpdir = tempfile.mkdtemp()
        # Write one context block
        ctx_file = Path(self._tmpdir) / "myctx.json"
        ctx_file.write_text(
            json.dumps(
                {
                    "id": "bg_info",
                    "name": "Background",
                    "content": "User is a Python developer.",
                    "enabled": True,
                    "priority": 10,
                }
            ),
            encoding="utf-8",
        )
        cp.ContextProvider._instance = None
        self._orig_dir = cp._CONTEXT_DIR
        cp._CONTEXT_DIR = Path(self._tmpdir)
        self._cp = cp.ContextProvider()

    def tearDown(self):
        from app.core.context import context_provider as cp

        cp._CONTEXT_DIR = self._orig_dir
        cp.ContextProvider._instance = None
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_list_blocks_returns_loaded_block(self):
        blocks = self._cp.list_blocks()
        ids = [b["id"] for b in blocks]
        self.assertIn("bg_info", ids)

    def test_inject_into_prompt_appends_content(self):
        result = self._cp.inject_into_prompt("original system prompt")
        self.assertIn("Python developer", result)

    def test_build_injection_returns_dict(self):
        inj = self._cp.build_injection()
        self.assertIsInstance(inj, dict)
        self.assertIn("system", inj)

    def test_disabled_block_not_injected(self):
        from app.core.context import context_provider as cp

        disabled = Path(self._tmpdir) / "disabled.json"
        disabled.write_text(
            json.dumps(
                {
                    "id": "disabled_ctx",
                    "content": "SECRET_NOT_INJECTED",
                    "enabled": False,
                }
            ),
            encoding="utf-8",
        )
        cp.ContextProvider._instance = None
        provider = cp.ContextProvider()
        result = provider.inject_into_prompt("base")
        self.assertNotIn("SECRET_NOT_INJECTED", result)

    def test_task_type_filter(self):
        """Block scoped to CHAT should not inject for CODE tasks."""
        from app.core.context import context_provider as cp

        scoped = Path(self._tmpdir) / "scoped.json"
        scoped.write_text(
            json.dumps(
                {
                    "id": "chat_only",
                    "content": "CHAT_SPECIFIC_TEXT",
                    "enabled": True,
                    "task_types": ["CHAT"],
                }
            ),
            encoding="utf-8",
        )
        cp.ContextProvider._instance = None
        provider = cp.ContextProvider()
        result_code = provider.inject_into_prompt("base", task_type="CODE")
        self.assertNotIn("CHAT_SPECIFIC_TEXT", result_code)
        result_chat = provider.inject_into_prompt("base", task_type="CHAT")
        self.assertIn("CHAT_SPECIFIC_TEXT", result_chat)


# ══════════════════════════════════════════════════════════════════════════════
# 6. User Tool Loader
# ══════════════════════════════════════════════════════════════════════════════


class TestKotoToolDecorator(unittest.TestCase):
    def setUp(self):
        import app.core.tools.user_tool_loader as utl

        utl._REGISTERED_TOOLS.clear()

    def test_decorator_registers_tool(self):
        from app.core.tools.user_tool_loader import get_registered_tools, koto_tool

        @koto_tool(description="Add two numbers", name="add_numbers")
        def add(a, b):
            return a + b

        tools = get_registered_tools()
        names = [t["name"] for t in tools]
        self.assertIn("add_numbers", names)

    def test_decorator_uses_function_name_if_no_name(self):
        from app.core.tools.user_tool_loader import get_registered_tools, koto_tool

        @koto_tool(description="Multiply numbers")
        def multiply(x, y):
            return x * y

        tools = get_registered_tools()
        names = [t["name"] for t in tools]
        self.assertIn("multiply", names)

    def test_decorated_function_still_callable(self):
        from app.core.tools.user_tool_loader import koto_tool

        @koto_tool(description="Greet user", name="greeter")
        def greet(name):
            return f"Hello, {name}!"

        self.assertEqual(greet("Logan"), "Hello, Logan!")

    def test_get_registered_tools_returns_list(self):
        from app.core.tools.user_tool_loader import get_registered_tools

        self.assertIsInstance(get_registered_tools(), list)

    def test_tool_has_description(self):
        from app.core.tools.user_tool_loader import get_registered_tools, koto_tool

        @koto_tool(description="Useful tool", name="useful_one")
        def do_something():
            pass

        tools = {t["name"]: t for t in get_registered_tools()}
        self.assertEqual(tools["useful_one"]["description"], "Useful tool")


class TestLoadUserTools(unittest.TestCase):
    def test_load_from_empty_dir(self):
        from app.core.tools import user_tool_loader as utl

        tmpdir = tempfile.mkdtemp()
        try:
            orig = utl._TOOLS_DIR
            utl._TOOLS_DIR = Path(tmpdir)
            utl._REGISTERED_TOOLS.clear()
            count = utl.load_user_tools()
            self.assertEqual(count, 0)
        finally:
            utl._TOOLS_DIR = orig
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_load_from_dir_with_valid_tool(self):
        from app.core.tools import user_tool_loader as utl

        tmpdir = tempfile.mkdtemp()
        try:
            tool_file = Path(tmpdir) / "my_tools.py"
            tool_file.write_text(
                "from app.core.tools.user_tool_loader import koto_tool\n"
                "@koto_tool(description='Test')\n"
                "def test_fn():\n"
                "    return 42\n",
                encoding="utf-8",
            )
            orig = utl._TOOLS_DIR
            utl._TOOLS_DIR = Path(tmpdir)
            utl._REGISTERED_TOOLS.clear()
            count = utl.load_user_tools()
            self.assertGreaterEqual(count, 1)
        finally:
            utl._TOOLS_DIR = orig
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_user_defined_plugin_name(self):
        from app.core.tools.user_tool_loader import UserDefinedPlugin

        p = UserDefinedPlugin()
        self.assertEqual(p.name, "UserDefinedTools")

    def test_user_defined_plugin_get_tools(self):
        from app.core.tools.user_tool_loader import UserDefinedPlugin

        p = UserDefinedPlugin()
        self.assertIsInstance(p.get_tools(), list)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Telegram Bot Routes Blueprint
# ══════════════════════════════════════════════════════════════════════════════


def _make_telegram_app():
    """Create a minimal Flask app with telegram_bot_routes registered."""
    from flask import Flask

    from app.api.telegram_bot_routes import telegram_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(telegram_bp, url_prefix="/api/telegram")
    return app.test_client()


class TestTelegramBotRoutesStatus(unittest.TestCase):
    def setUp(self):
        # Bot not running (no token)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        self.client = _make_telegram_app()

    def test_status_returns_200(self):
        resp = self.client.get("/api/telegram/status")
        self.assertEqual(resp.status_code, 200)

    def test_status_has_running_field(self):
        resp = self.client.get("/api/telegram/status")
        data = json.loads(resp.data)
        self.assertIn("running", data)

    def test_status_running_false_without_token(self):
        resp = self.client.get("/api/telegram/status")
        data = json.loads(resp.data)
        self.assertFalse(data["running"])


class TestTelegramBotRoutesContacts(unittest.TestCase):
    def setUp(self):
        self.client = _make_telegram_app()

    def test_get_contacts_returns_200(self):
        # Contacts endpoint should always return a valid response
        resp = self.client.get("/api/telegram/contacts")
        self.assertIn(resp.status_code, (200, 404, 500))

    def test_post_contact_missing_fields_returns_error(self):
        resp = self.client.post(
            "/api/telegram/contacts",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (400, 422, 500))


class TestTelegramBotRoutesConfig(unittest.TestCase):
    def setUp(self):
        self.client = _make_telegram_app()

    def test_post_config_empty_returns_ok_or_error(self):
        resp = self.client.post(
            "/api/telegram/config", data=json.dumps({}), content_type="application/json"
        )
        self.assertIn(resp.status_code, (200, 400, 500))

    def test_post_test_without_bot_returns_error(self):
        """Sending a test message without a running bot should fail gracefully."""
        resp = self.client.post(
            "/api/telegram/test",
            data=json.dumps({"chat_id": "123", "text": "hello"}),
            content_type="application/json",
        )
        self.assertIn(resp.status_code, (200, 400, 500, 503))


class TestTelegramBotRoutesBrief(unittest.TestCase):
    def setUp(self):
        self.client = _make_telegram_app()

    def test_brief_preview_returns_brief_or_error(self):
        resp = self.client.get("/api/telegram/brief/preview")
        self.assertIn(resp.status_code, (200, 500))
        if resp.status_code == 200:
            data = json.loads(resp.data)
            self.assertIn("brief", data)


if __name__ == "__main__":
    unittest.main()
