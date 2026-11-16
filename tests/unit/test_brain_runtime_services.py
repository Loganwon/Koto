from __future__ import annotations

from app.core.brain import BrainRuntimeServices, KotoBrain


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
        select_model_for_task=lambda *_args, **_kwargs: "deepseek-chat",
        get_utils=lambda: _Utils,
        get_local_executor=lambda: _Executor,
        get_workspace_dir=lambda: "",
        get_settings_manager=lambda: object(),
        get_model_map=lambda: {},
    )

    result = KotoBrain(runtime).chat([], "inspect system", task_type="SYSTEM")

    assert result["task"] == "SYSTEM"
    assert result["route_method"] == "Manual select"
    assert result["response"] == "completed\n\ninjected runtime"


def test_brain_defaults_to_stable_chat_without_inferring_intent():
    class _Gateway:
        @staticmethod
        def generate_content(*, model, contents):
            return type("Response", (), {"text": "chat response"})()

    runtime = BrainRuntimeServices(
        select_model_for_task=lambda *_args, **_kwargs: "deepseek-chat",
        get_utils=lambda: _Utils,
        get_local_executor=lambda: _Executor,
        get_workspace_dir=lambda: "",
        get_settings_manager=lambda: object(),
        get_model_map=lambda: {},
        get_llm_gateway=lambda: _Gateway(),
    )

    result = KotoBrain(runtime).chat([], "inspect system")

    assert result["task"] == "CHAT"
    assert result["route_method"] == "Stable chat boundary"
    assert result["response"] == "chat response"
