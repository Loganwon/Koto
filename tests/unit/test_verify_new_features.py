"""
Verification tests for all new features added across multiple sessions.

Categories:
  A. SkillAutoMatcher — _detect_conflicts / _CONFLICT_PAIRS
  B. SkillAutoMatcher — rating-aware scoring in match()
  C. SkillSuggester — Layer 4 rating scoring in _score_candidates
  D. TaskLedger — TaskPriority enum + set_priority + list ordering
  E. MultiAgentOrchestrator — AgentRole.model_id override field
  F. MultiAgentOrchestrator — parallel_roles accepted in __init__
  G. MultiAgentOrchestrator — preset_analysis_pipeline classmethod
  H. MultiAgentOrchestrator — timeout param in run()
"""

from __future__ import annotations

import os
import tempfile
import uuid
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# A. SkillAutoMatcher — _detect_conflicts
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
            AM,
            "_rating_for",
            side_effect=lambda sid: 4.0 if sid == "research_depth" else 2.0,
        )
        result = AM._detect_conflicts(["concise_mode", "research_depth"])
        assert "concise_mode" not in result
        assert "research_depth" in result

    def test_conflict_removes_multiple_losers(self, mocker):
        AM = self._matcher()
        mocker.patch.object(
            AM,
            "_rating_for",
            side_effect=lambda sid: {"professional_tone": 4.5, "casual_style": 2.0}.get(
                sid, 3.0
            ),
        )
        result = AM._detect_conflicts(
            ["professional_tone", "casual_style", "step_by_step"]
        )
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
        from app.core.skills.skill_auto_matcher import _DEFAULT_RATING, SkillAutoMatcher

        mocker.patch(
            "app.core.skills.skill_auto_matcher.Path.read_text",
            return_value="{}",
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
        score_default = SS._score_candidates(
            "test", [base_candidate], "CHAT", ratings={}
        )[0][0]
        score_high = SS._score_candidates(
            "test", [base_candidate], "CHAT", ratings={"skill_a": 5.0}
        )[0][0]
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

        score_default = SS._score_candidates("test", [candidate], "CHAT", ratings={})[
            0
        ][0]
        score_low = SS._score_candidates(
            "test", [candidate], "CHAT", ratings={"skill_b": 1.0}
        )[0][0]
        assert score_low < score_default, "Low rating should reduce score"

    def test_load_ratings_returns_dict(self, mocker):
        SS = self._suggester()
        mocker.patch(
            "builtins.open", mocker.mock_open(read_data='{"sk1": {"avg": 4.5}}')
        )
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
            rec = ledger.create(
                "sess1", "test input", source="test", priority=TaskPriority.HIGH
            )
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
            ledger.create(
                "sess1", "urgent", source="test", priority=TaskPriority.URGENT
            )
            ledger.create(
                "sess1", "normal", source="test", priority=TaskPriority.NORMAL
            )
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

        role = AgentRole(
            name="test", display_name="Test", system_prompt="", output_field="output"
        )
        assert role.model_id is None

    def test_model_id_can_be_set(self):
        from app.core.agent.multi_agent import AgentRole

        role = AgentRole(
            name="test",
            display_name="Test",
            system_prompt="",
            output_field="output",
            model_id="gemini-pro",
        )
        assert role.model_id == "gemini-pro"

    def test_roles_registry_has_no_model_id_override(self):
        """Predefined ROLES should have model_id=None (orchestrator-level default)."""
        from app.core.agent.multi_agent import ROLES

        for attr in (
            "RESEARCHER",
            "WRITER",
            "CRITIC",
            "CODER",
            "REVIEWER",
            "DATA_ANALYST",
        ):
            role = getattr(ROLES, attr)
            assert (
                role.model_id is None
            ), f"ROLES.{attr}.model_id should default to None"


# ─────────────────────────────────────────────────────────────────────────────
# I. MultiAgentOrchestrator — parallel_roles in __init__
# ─────────────────────────────────────────────────────────────────────────────
class TestMultiAgentParallelRoles:
    def test_parallel_roles_defaults_to_empty(self):
        from app.core.agent.multi_agent import ROLES, MultiAgentOrchestrator

        orch = MultiAgentOrchestrator(roles=[ROLES.RESEARCHER])
        assert orch.parallel_roles == []

    def test_parallel_roles_stored(self):
        from app.core.agent.multi_agent import ROLES, MultiAgentOrchestrator

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
        import inspect

        from app.core.agent.multi_agent import MultiAgentOrchestrator

        sig = inspect.signature(MultiAgentOrchestrator.run)
        assert "timeout" in sig.parameters, "run() must have a 'timeout' parameter"

    def test_run_timeout_type_annotation(self):
        import inspect

        from app.core.agent.multi_agent import MultiAgentOrchestrator

        sig = inspect.signature(MultiAgentOrchestrator.run)
        param = sig.parameters["timeout"]
        # default should be None (Optional[float])
        assert param.default is None
