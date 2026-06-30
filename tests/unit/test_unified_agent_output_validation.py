import sys
import types

import app.core.agent.unified_agent as unified_agent_module
from app.core.agent.types import AgentStepType
from app.core.agent.unified_agent import UnifiedAgent
from app.core.llm.base import LLMProvider


class _PlaceholderProvider(LLMProvider):
    def generate_content(self, prompt, model, **kwargs):
        return {
            "content": "Koto 后台运行平稳，关键模块 <<姓名-1>> 已成功加载并处于就绪状态。",
            "tool_calls": [],
        }

    def get_token_count(self, prompt, model):
        return 1


def test_unified_agent_sanitizes_blocked_placeholder_text_before_user_visible_steps(
    monkeypatch,
):
    class _FakeLedger:
        def create(self, **kwargs):
            return types.SimpleNamespace(task_id="task-1")

        def mark_running(self, task_id):
            return None

        def add_step(self, task_id, **kwargs):
            return None

        def mark_completed(self, task_id, result_summary=None):
            return None

    class _FakeProgressBus:
        def publish_step(self, *args, **kwargs):
            return None

    class _FakeSkillManager:
        _registry = {}

        @staticmethod
        def inject_into_prompt(base_system_instruction, **kwargs):
            return base_system_instruction

        @staticmethod
        def get_definition(skill_id):
            return None

    class _FakeSkillAutoMatcher:
        @staticmethod
        def match(**kwargs):
            return []

    class _FakeSkillBindingManager:
        def ensure_recommended_bindings(self):
            return None

        def match_intent(self, safe_input):
            return []

    class _FakeContextProvider:
        def inject_into_prompt(self, prompt, **kwargs):
            return prompt

    monkeypatch.setattr(unified_agent_module, "_get_task_ledger", lambda: _FakeLedger())
    monkeypatch.setattr(
        unified_agent_module,
        "_get_progress_bus",
        lambda: (_FakeProgressBus(), object),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.core.skills.skill_manager",
        types.SimpleNamespace(SkillManager=_FakeSkillManager),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.core.skills.skill_auto_matcher",
        types.SimpleNamespace(SkillAutoMatcher=_FakeSkillAutoMatcher),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.core.skills.skill_trigger_binding",
        types.SimpleNamespace(SkillBindingManager=_FakeSkillBindingManager),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.core.context.context_provider",
        types.SimpleNamespace(
            get_context_provider=lambda: _FakeContextProvider(),
        ),
    )

    agent = UnifiedAgent(
        llm_provider=_PlaceholderProvider(),
        model_id="test-model",
        enable_pii_filter=False,
        enable_output_validation=True,
    )

    steps = list(agent.run("检查当前系统状态"))
    thought_steps = [step for step in steps if step.step_type == AgentStepType.THOUGHT]
    answer_steps = [step for step in steps if step.step_type == AgentStepType.ANSWER]

    step_dump = [(str(step.step_type), step.content, step.metadata) for step in steps]

    assert thought_steps, step_dump
    assert answer_steps, step_dump
    assert all(
        "<<姓名-1>>" not in (step.content or "") for step in thought_steps
    ), step_dump
    assert all(
        "<<姓名-1>>" not in (step.content or "") for step in answer_steps
    ), step_dump
    assert answer_steps[-1].content.startswith("抱歉"), step_dump
    assert answer_steps[-1].metadata["validation_action"] == "WARN"
