from __future__ import annotations

from pathlib import Path

from app.core.llm import model_selection


class _Fallback:
    @staticmethod
    def is_available(_model):
        return True


def _stable_selection(monkeypatch):
    monkeypatch.setattr(
        model_selection,
        "get_configured_cloud_model",
        lambda task_type, fallback_model: fallback_model,
    )
    monkeypatch.setattr(
        "app.core.llm.model_fallback.get_fallback_executor",
        lambda: _Fallback(),
    )


def test_select_task_model_uses_explicit_task_contract(monkeypatch):
    _stable_selection(monkeypatch)

    assert (
        model_selection.select_task_model(
            "CODER", model_map={"CHAT": "chat", "CODER": "code"}
        )
        == "code"
    )


def test_select_task_model_uses_complex_and_image_capabilities(monkeypatch):
    _stable_selection(monkeypatch)
    mapping = {
        "CHAT": "chat",
        "COMPLEX": "reasoning",
        "VISION": "vision",
    }

    assert (
        model_selection.select_task_model(
            "CHAT", model_map=mapping, complexity="complex"
        )
        == "reasoning"
    )
    assert (
        model_selection.select_task_model("CHAT", model_map=mapping, has_image=True)
        == "vision"
    )


def test_model_selection_source_contains_no_free_text_router():
    text = Path(model_selection.__file__).read_text(encoding="utf-8")

    assert "user_input" not in text
    assert "TASK_CORPUS" not in text
    assert "def analyze(" not in text
    assert "def classify(" not in text
