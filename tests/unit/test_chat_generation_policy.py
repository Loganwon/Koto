from app.core.llm.chat_generation_policy import (
    DEFAULT_CHAT_MODEL,
    first_token_timeout_seconds,
    select_regular_model,
)


def test_select_regular_model_prefers_task_then_chat_then_default():
    assert (
        select_regular_model("CODER", {"CHAT": "chat-model", "CODER": "coder-model"})
        == "coder-model"
    )
    assert select_regular_model("RESEARCH", {"CHAT": "chat-model"}) == "chat-model"
    assert select_regular_model("CHAT", {}) == DEFAULT_CHAT_MODEL


def test_first_token_timeout_seconds_keeps_coder_shorter():
    assert first_token_timeout_seconds("CODER") == 60
    assert first_token_timeout_seconds("CHAT") == 120
