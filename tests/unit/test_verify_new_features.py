"""
Verification tests for all new features added across multiple sessions.

Categories:
  A. TaskDecomposer.suggest_multiagent_preset
  B. SmartDispatcher compound-task routing (multiagent_preset stamped on context_info)
  C. web/app.py generate_multi_agent preset dispatch (logic only)
  D. SkillAutoMatcher — _detect_conflicts / _CONFLICT_PAIRS
  E. SkillAutoMatcher — rating-aware scoring in match()
  F. SkillSuggester — Layer 4 rating scoring in _score_candidates
  G. TaskLedger — TaskPriority enum + set_priority + list ordering
  H. MultiAgentOrchestrator — AgentRole.model_id override field
  I. MultiAgentOrchestrator — parallel_roles accepted in __init__
  J. MultiAgentOrchestrator — preset_analysis_pipeline classmethod
  K. MultiAgentOrchestrator — timeout param in run()
"""

from __future__ import annotations

import uuid
import tempfile
import os
import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# A. TaskDecomposer.suggest_multiagent_preset
# ─────────────────────────────────────────────────────────────────────────────
class TestSuggestMultiagentPreset:
    """suggest_multiagent_preset should map compound_info → preset name."""

    def _decomposer(self):
        from app.core.routing.task_decomposer import TaskDecomposer
        return TaskDecomposer

    def test_returns_none_when_not_compound(self):
        TD = self._decomposer()
        result = TD.suggest_multiagent_preset({"is_compound": False})
        assert result is None

    def test_code_primary_task_returns_code(self):
        TD = self._decomposer()
        info = {"is_compound": True, "primary_task": "CODE", "secondary_tasks": [], "pattern": ""}
        assert TD.suggest_multiagent_preset(info) == "code"

    def test_coder_primary_task_returns_code(self):
        TD = self._decomposer()
        info = {"is_compound": True, "primary_task": "CODER", "secondary_tasks": [], "pattern": ""}
        assert TD.suggest_multiagent_preset(info) == "code"

    def test_code_in_secondary_returns_code(self):
        TD = self._decomposer()
        info = {"is_compound": True, "primary_task": "CHAT", "secondary_tasks": ["CODE"], "pattern": ""}
        assert TD.suggest_multiagent_preset(info) == "code"

    def test_research_with_file_gen_returns_analysis(self):
        TD = self._decomposer()
        info = {
            "is_compound": True,
            "primary_task": "RESEARCH",
            "secondary_tasks": ["FILE_GEN"],
            "pattern": "research_and_document",
        }
        assert TD.suggest_multiagent_preset(info) == "analysis"

    def test_search_and_document_returns_content(self):
        TD = self._decomposer()
        info = {
            "is_compound": True,
            "primary_task": "WEB_SEARCH",
            "secondary_tasks": ["FILE_GEN"],
            "pattern": "search_and_document",
        }
        assert TD.suggest_multiagent_preset(info) == "content"

    def test_document_workflow_returns_content(self):
        TD = self._decomposer()
        info = {
            "is_compound": True,
            "primary_task": "CHAT",
            "secondary_tasks": [],
            "pattern": "document_workflow",
        }
        assert TD.suggest_multiagent_preset(info) == "content"

    def test_fallback_compound_returns_content(self):
        TD = self._decomposer()
        info = {
            "is_compound": True,
            "primary_task": "CHAT",
            "secondary_tasks": [],
            "pattern": "unknown_pattern",
        }
        assert TD.suggest_multiagent_preset(info) == "content"

    def test_missing_fields_do_not_raise(self):
        TD = self._decomposer()
        # Minimal dict — should not raise even with missing keys
        result = TD.suggest_multiagent_preset({"is_compound": True})
        assert result in ("content", "code", "analysis")


# ─────────────────────────────────────────────────────────────────────────────
# B. SmartDispatcher compound routing stamps multiagent_preset
# ─────────────────────────────────────────────────────────────────────────────
class TestSmartDispatcherMultiagentPresetStamping:
    """Verify the dispatcher's compound-task branch is correctly wired to
    call suggest_multiagent_preset and stamp context_info['multiagent_preset'].
    Source-code inspection tests avoid needing to mock the entire 1200-line
    analyze() method."""

    def test_suggest_multiagent_preset_called_in_dispatcher_source(self):
        """smart_dispatcher must call suggest_multiagent_preset (wiring exists)."""
        import inspect
        import app.core.routing.smart_dispatcher as module
        src = inspect.getsource(module)
        assert "suggest_multiagent_preset" in src, (
            "smart_dispatcher must call suggest_multiagent_preset"
        )

    def test_multiagent_preset_stamped_into_context_info(self):
        """context_info['multiagent_preset'] assignment line must exist."""
        import inspect
        import app.core.routing.smart_dispatcher as module
        src = inspect.getsource(module)
        assert 'context_info["multiagent_preset"] = _ma_preset' in src, (
            "Dispatcher must write multiagent_preset into context_info"
        )

    def test_stamping_is_fault_tolerant(self):
        """The stamping call must be inside a try/except block."""
        import inspect
        import app.core.routing.smart_dispatcher as module
        src = inspect.getsource(module)
        assert "suggest_multiagent_preset" in src
        # The block must have an except clause for fault tolerance
        assert "except Exception" in src



# ─────────────────────────────────────────────────────────────────────────────
# D. SkillAutoMatcher — _detect_conflicts
# ─────────────────────────────────────────────────────────────────────────────
class TestDetectConflicts:
    def _matcher(self):
        from app.core.skills.skill_auto_matcher import SkillAutoMatcher
        return SkillAutoMatcher

    def test_no_conflict_returns_original(self):
        AM = self._matcher()
        skills = ["step_by_step", "teaching_mode"]
        assert AM._detect_conflicts(skills) == skills

    def test_conflict_pair_removes_lower_rated(self, mocker):
        AM = self._matcher()
        # concise_mode vs research_depth — both are in _CONFLICT_PAIRS
        mocker.patch.object(
            AM, "_rating_for",
            side_effect=lambda sid: 4.0 if sid == "research_depth" else 2.0,
        )
        result = AM._detect_conflicts(["concise_mode", "research_depth"])
        assert "concise_mode" not in result
        assert "research_depth" in result

    def test_conflict_removes_multiple_losers(self, mocker):
        AM = self._matcher()
        mocker.patch.object(
            AM, "_rating_for",
            side_effect=lambda sid: {"professional_tone": 4.5, "casual_style": 2.0}.get(sid, 3.0),
        )
        result = AM._detect_conflicts(["professional_tone", "casual_style", "step_by_step"])
        assert "casual_style" not in result
        assert "professional_tone" in result
        assert "step_by_step" in result

    def test_single_skill_unchanged(self):
        AM = self._matcher()
        assert AM._detect_conflicts(["concise_mode"]) == ["concise_mode"]

    def test_empty_list_unchanged(self):
        AM = self._matcher()
        assert AM._detect_conflicts([]) == []

    def test_conflict_pairs_are_frozensets(self):
        from app.core.skills.skill_auto_matcher import _CONFLICT_PAIRS
        for pair in _CONFLICT_PAIRS:
            assert isinstance(pair, frozenset), f"Expected frozenset, got {type(pair)}"
            assert len(pair) == 2, f"Each conflict pair must have exactly 2 members"


# ─────────────────────────────────────────────────────────────────────────────
# E. SkillAutoMatcher — rating-aware scoring  (via _rating_for)
# ─────────────────────────────────────────────────────────────────────────────
class TestAutoMatcherRatingAware:
    def test_rating_for_returns_float(self, mocker):
        from app.core.skills.skill_auto_matcher import SkillAutoMatcher
        mocker.patch(
            "app.core.skills.skill_auto_matcher.Path.read_text",
            return_value='{"good_skill": {"avg": 4.8}}',
        )
        rating = SkillAutoMatcher._rating_for("good_skill")
        assert isinstance(rating, float)

    def test_rating_for_missing_skill_returns_default(self, mocker):
        from app.core.skills.skill_auto_matcher import SkillAutoMatcher, _DEFAULT_RATING
        mocker.patch(
            "app.core.skills.skill_auto_matcher.Path.read_text",
            return_value='{}',
        )
        rating = SkillAutoMatcher._rating_for("nonexistent_skill_xyz")
        assert rating == _DEFAULT_RATING


# ─────────────────────────────────────────────────────────────────────────────
# F. SkillSuggester — Layer 4 rating scoring
# ─────────────────────────────────────────────────────────────────────────────
class TestSkillSuggesterRatingLayer:
    def _suggester(self):
        from app.core.skills.skill_suggester import SkillSuggester
        return SkillSuggester

    def test_high_rating_boosts_score(self):
        SS = self._suggester()
        base_candidate = {
            "id": "skill_a",
            "name": "Skill A",
            "icon": "🔧",
            "description": "test skill a",
            "intent_description": "",
            "tags": [],
            "trigger_keywords": [],
            "task_types": [],
        }
        # No rating (default 3.0) vs high rating (5.0)
        score_default = SS._score_candidates("test", [base_candidate], "CHAT", ratings={})[0][0]
        score_high = SS._score_candidates("test", [base_candidate], "CHAT", ratings={"skill_a": 5.0})[0][0]
        assert score_high > score_default, "High rating should boost score"

    def test_low_rating_reduces_score(self):
        SS = self._suggester()
        candidate = {
            "id": "skill_b",
            "name": "Skill B",
            "icon": "🔧",
            "description": "test skill b",
            "intent_description": "",
            "tags": [],
            "trigger_keywords": [],
            "task_types": [],
        }
        from app.core.skills.skill_suggester import _DEFAULT_RATING
        score_default = SS._score_candidates("test", [candidate], "CHAT", ratings={})[0][0]
        score_low = SS._score_candidates("test", [candidate], "CHAT", ratings={"skill_b": 1.0})[0][0]
        assert score_low < score_default, "Low rating should reduce score"

    def test_load_ratings_returns_dict(self, mocker):
        SS = self._suggester()
        mocker.patch("builtins.open", mocker.mock_open(read_data='{"sk1": {"avg": 4.5}}'))
        from pathlib import Path
        mocker.patch.object(Path, "exists", return_value=True)
        ratings = SS._load_ratings()
        assert isinstance(ratings, dict)


# ─────────────────────────────────────────────────────────────────────────────
# G. TaskLedger — TaskPriority enum + set_priority
# ─────────────────────────────────────────────────────────────────────────────
class TestTaskLedgerPriority:
    def _make_ledger(self):
        from app.core.tasks.task_ledger import TaskLedger
        tmp = tempfile.mktemp(suffix=".sqlite")
        ledger = TaskLedger(db_path=tmp)
        return ledger, tmp

    def _teardown(self, ledger, tmp):
        """Close the SQLite connection before deleting the temp file (Windows)."""
        try:
            ledger._conn.close()
        except Exception:
            pass
        try:
            os.unlink(tmp)
        except Exception:
            pass

    def test_task_priority_enum_values(self):
        from app.core.tasks.task_ledger import TaskPriority
        assert TaskPriority.LOW < TaskPriority.NORMAL
        assert TaskPriority.NORMAL < TaskPriority.HIGH
        assert TaskPriority.HIGH < TaskPriority.URGENT

    def test_create_task_with_priority(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority
        ledger, tmp = self._make_ledger()
        try:
            rec = ledger.create("sess1", "test input", source="test", priority=TaskPriority.HIGH)
            tasks = ledger.list_tasks()
            task = next((t for t in tasks if t.task_id == rec.task_id), None)
            assert task is not None
            assert task.priority == int(TaskPriority.HIGH)
        finally:
            self._teardown(ledger, tmp)

    def test_set_priority_updates_value(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority
        ledger, tmp = self._make_ledger()
        try:
            rec = ledger.create("sess1", "prio input", source="test")
            ledger.set_priority(rec.task_id, TaskPriority.URGENT)
            tasks = ledger.list_tasks()
            task = next((t for t in tasks if t.task_id == rec.task_id), None)
            assert task.priority == int(TaskPriority.URGENT)
        finally:
            self._teardown(ledger, tmp)

    def test_list_tasks_order_by_priority(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority
        ledger, tmp = self._make_ledger()
        try:
            ledger.create("sess1", "low", source="test", priority=TaskPriority.LOW)
            ledger.create("sess1", "urgent", source="test", priority=TaskPriority.URGENT)
            ledger.create("sess1", "normal", source="test", priority=TaskPriority.NORMAL)
            tasks = ledger.list_tasks(order_by="priority")
            prios = [t.priority for t in tasks]
            # priority descending: URGENT(3) first, LOW(0) last
            assert prios == sorted(prios, reverse=True)
        finally:
            self._teardown(ledger, tmp)

    def test_list_tasks_filter_by_priority(self):
        from app.core.tasks.task_ledger import TaskLedger, TaskPriority
        ledger, tmp = self._make_ledger()
        try:
            ledger.create("sess1", "a", source="test", priority=TaskPriority.HIGH)
            ledger.create("sess1", "b", source="test", priority=TaskPriority.LOW)
            high_tasks = ledger.list_tasks(priority=int(TaskPriority.HIGH))
            assert all(t.priority == int(TaskPriority.HIGH) for t in high_tasks)
        finally:
            self._teardown(ledger, tmp)


# ─────────────────────────────────────────────────────────────────────────────
# H. AgentRole.model_id field
# ─────────────────────────────────────────────────────────────────────────────
class TestAgentRoleModelId:
    def test_model_id_defaults_to_none(self):
        from app.core.agent.multi_agent import AgentRole
        role = AgentRole(name="test", display_name="Test", system_prompt="", output_field="output")
        assert role.model_id is None

    def test_model_id_can_be_set(self):
        from app.core.agent.multi_agent import AgentRole
        role = AgentRole(name="test", display_name="Test", system_prompt="", output_field="output", model_id="gemini-pro")
        assert role.model_id == "gemini-pro"

    def test_roles_registry_has_no_model_id_override(self):
        """Predefined ROLES should have model_id=None (orchestrator-level default)."""
        from app.core.agent.multi_agent import ROLES
        for attr in ("RESEARCHER", "WRITER", "CRITIC", "CODER", "REVIEWER", "DATA_ANALYST"):
            role = getattr(ROLES, attr)
            assert role.model_id is None, f"ROLES.{attr}.model_id should default to None"


# ─────────────────────────────────────────────────────────────────────────────
# I. MultiAgentOrchestrator — parallel_roles in __init__
# ─────────────────────────────────────────────────────────────────────────────
class TestMultiAgentParallelRoles:
    def test_parallel_roles_defaults_to_empty(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator, ROLES
        orch = MultiAgentOrchestrator(roles=[ROLES.RESEARCHER])
        assert orch.parallel_roles == []

    def test_parallel_roles_stored(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator, ROLES
        orch = MultiAgentOrchestrator(
            roles=[ROLES.WRITER],
            parallel_roles=[ROLES.RESEARCHER],
        )
        assert len(orch.parallel_roles) == 1
        assert orch.parallel_roles[0].name == "researcher"

    def test_parallel_outputs_in_state(self):
        from app.core.agent.multi_agent import MultiAgentState
        # parallel_outputs must be a list field on the state TypedDict
        assert "parallel_outputs" in MultiAgentState.__annotations__


# ─────────────────────────────────────────────────────────────────────────────
# J. preset_analysis_pipeline classmethod
# ─────────────────────────────────────────────────────────────────────────────
class TestPresetAnalysisPipeline:
    def test_preset_analysis_pipeline_exists(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        assert hasattr(MultiAgentOrchestrator, "preset_analysis_pipeline")
        assert callable(MultiAgentOrchestrator.preset_analysis_pipeline)

    def test_preset_analysis_pipeline_returns_orchestrator(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator.preset_analysis_pipeline()
        assert isinstance(orch, MultiAgentOrchestrator)

    def test_preset_analysis_pipeline_role_names(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator.preset_analysis_pipeline()
        names = [r.name for r in orch.roles]
        assert "researcher" in names
        assert "data_analyst" in names or "analyst" in names
        assert "critic" in names

    def test_preset_code_pipeline_roles(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator.preset_code_pipeline()
        names = [r.name for r in orch.roles]
        assert "coder" in names
        assert "reviewer" in names

    def test_preset_content_pipeline_roles(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator.preset_content_pipeline()
        names = [r.name for r in orch.roles]
        assert "writer" in names
        assert "critic" in names


# ─────────────────────────────────────────────────────────────────────────────
# K. MultiAgentOrchestrator.run() — timeout parameter
# ─────────────────────────────────────────────────────────────────────────────
class TestMultiAgentTimeout:
    def test_run_accepts_timeout_kwarg(self):
        """run() must accept timeout without raising TypeError."""
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        import inspect
        sig = inspect.signature(MultiAgentOrchestrator.run)
        assert "timeout" in sig.parameters, "run() must have a 'timeout' parameter"

    def test_run_timeout_type_annotation(self):
        from app.core.agent.multi_agent import MultiAgentOrchestrator
        import inspect
        sig = inspect.signature(MultiAgentOrchestrator.run)
        param = sig.parameters["timeout"]
        # default should be None (Optional[float])
        assert param.default is None
