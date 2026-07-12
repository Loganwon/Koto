from __future__ import annotations

from app.core.brain import BrainRuntimeServices, KotoBrain


class _Dispatcher:
    @staticmethod
    def analyze(_user_input: str):
        return "SYSTEM", "test", {}

    @staticmethod
    def get_model_for_task(_target_key: str, *, has_image: bool = False):
        return "deepseek-chat"


class _Executor:
    @staticmethod
    def execute(_user_input: str):
        return {"message": "completed", "details": "injected runtime"}


class _Utils:
    @staticmethod
    def adapt_prompt_to_markdown(_target_key: str, text: str, *, history):
        return text


def test_brain_uses_injected_runtime_services_for_system_tasks():
    runtime = BrainRuntimeServices(
        get_smart_dispatcher=lambda: _Dispatcher,
        get_utils=lambda: _Utils,
        get_local_executor=lambda: _Executor,
        get_client=lambda: object(),
        get_workspace_dir=lambda: "",
        get_settings_manager=lambda: object(),
        get_model_map=lambda: {},
    )

    result = KotoBrain(runtime).chat([], "inspect system")

    assert result["task"] == "SYSTEM"
    assert result["response"] == "completed\n\ninjected runtime"
