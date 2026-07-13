from app.core.llm.chat_generation_policy import (
    DEFAULT_CHAT_MODEL,
    first_token_timeout_seconds,
    select_regular_model,
    should_try_local_chat_fast_path,
)


def test_select_regular_model_prefers_task_then_chat_then_default():
    assert (
        select_regular_model("CODER", {"CHAT": "chat-model", "CODER": "coder-model"})
        == "coder-model"
    )
    assert select_regular_model("RESEARCH", {"CHAT": "chat-model"}) == "chat-model"
    assert select_regular_model("CHAT", {}) == DEFAULT_CHAT_MODEL


def test_should_try_local_chat_fast_path_preserves_existing_gates():
    assert should_try_local_chat_fast_path(
        task_type="CHAT",
        locked_model="cloud",
        local_chat_override=False,
        simple_query=True,
    )
    assert should_try_local_chat_fast_path(
        task_type="CHAT",
        locked_model="cloud",
        local_chat_override=True,
        simple_query=False,
    )
    assert not should_try_local_chat_fast_path(
        task_type="CHAT",
        locked_model="local",
        local_chat_override=True,
        simple_query=True,
    )
    assert not should_try_local_chat_fast_path(
        task_type="CODER",
        locked_model="cloud",
        local_chat_override=True,
        simple_query=True,
    )


def test_first_token_timeout_seconds_keeps_coder_shorter():
    assert first_token_timeout_seconds("CODER") == 60
    assert first_token_timeout_seconds("CHAT") == 120
