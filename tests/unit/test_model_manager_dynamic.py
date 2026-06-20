from __future__ import annotations

from web.model_manager import ModelManager, _INFER_RULES, infer_capabilities
from app.core.llm.model_capabilities import is_interactions_only_model


class _FakeModel:
    def __init__(self, name: str, supported_actions=None):
        self.name = name
        self.supported_actions = supported_actions or []


class _FakeModelApi:
    def __init__(self, models):
        self._models = models

    def list(self, config=None):
        return list(self._models)


class _NoneModelApi:
    def list(self, config=None):
        return None


class _FakeClient:
    def __init__(self, models):
        self.models = _FakeModelApi(models)


class _NoneClient:
    def __init__(self):
        self.models = _NoneModelApi()


def _caps(speed: int, quality: int, reasoning: int, context: int, tier: int):
    return {
        "provider": "gemini",
        "speed": speed,
        "quality": quality,
        "reasoning": reasoning,
        "context": context,
        "tier": tier,
        "multimodal": True,
        "function_calling": True,
        "grounding": True,
        "image_gen": False,
        "interactions_only": False,
        "display": "x",
        "strengths": [],
    }


def test_interactions_only_detection_supports_prefix_and_normalization():
    assert is_interactions_only_model("models/deep-research-pro-preview-12-2025")
    assert is_interactions_only_model("deep-research-next-agent-preview")
    assert not is_interactions_only_model("gemini-3-flash-preview")
    assert not is_interactions_only_model("gemini-3.1-pro-preview")
    assert not is_interactions_only_model("gemini-2.5-flash")


def test_infer_capabilities_does_not_mutate_infer_rules():
    before = [rule[1].copy() for rule in _INFER_RULES]

    first = infer_capabilities("gemini-3.1-pro-preview")
    second = infer_capabilities("gemini-3.1-pro-preview")

    after = [rule[1].copy() for rule in _INFER_RULES]
    assert before == after
    assert first["tier"] == second["tier"]


def test_select_best_chat_prefers_flash_over_heavier_pro_when_available():
    manager = ModelManager(client=None)
    manager._cached_caps = {
        "gemini-2.5-pro": _caps(speed=10, quality=10, reasoning=10, context=10, tier=10),
        "gemini-2.5-flash": _caps(speed=3, quality=3, reasoning=3, context=3, tier=7),
    }

    best = manager._select_best("CHAT", ["gemini-2.5-pro", "gemini-2.5-flash"])
    assert best == "gemini-2.5-flash"


def test_fetch_available_model_ids_keeps_non_blocklisted_preview(monkeypatch):
    monkeypatch.delenv("KOTO_MODEL_BLOCKLIST", raising=False)

    client = _FakeClient(
        [
            _FakeModel("models/gemini-3.1-pro-preview", ["generateContent"]),
            _FakeModel("models/text-embedding-004", ["embedContent"]),
        ]
    )
    manager = ModelManager(client=client)

    ids = manager._fetch_available_model_ids()

    assert "gemini-3.1-pro-preview" in ids
    assert "text-embedding-004" not in ids


def test_fetch_available_model_ids_respects_env_blocklist(monkeypatch):
    monkeypatch.setenv("KOTO_MODEL_BLOCKLIST", "gemini-3.1-pro-preview")

    client = _FakeClient(
        [
            _FakeModel("models/gemini-3.1-pro-preview", ["generateContent"]),
            _FakeModel("models/gemini-2.5-flash", ["generateContent"]),
        ]
    )
    manager = ModelManager(client=client)

    ids = manager._fetch_available_model_ids()

    assert "gemini-3.1-pro-preview" not in ids
    assert "gemini-2.5-flash" in ids


def test_fetch_available_model_ids_treats_none_list_response_as_empty():
    manager = ModelManager(client=_NoneClient())

    ids = manager._fetch_available_model_ids()

    assert ids == []


def test_select_best_prefers_gemini3_flash_for_chat_when_available():
    manager = ModelManager(client=None)
    manager._cached_caps = {
        "gemini-3-flash-preview": _caps(speed=10, quality=8, reasoning=8, context=8, tier=8),
        "gemini-2.5-flash": _caps(speed=9, quality=7, reasoning=7, context=7, tier=7),
    }

    best = manager._select_best("CHAT", ["gemini-2.5-flash", "gemini-3-flash-preview"])
    assert best == "gemini-3-flash-preview"


def test_select_best_prefers_gemini31_pro_for_coder_when_available():
    manager = ModelManager(client=None)
    manager._cached_caps = {
        "gemini-3.1-pro-preview": _caps(speed=9, quality=10, reasoning=10, context=10, tier=10),
        "gemini-2.5-pro": _caps(speed=4, quality=10, reasoning=10, context=10, tier=9),
    }

    best = manager._select_best("CODER", ["gemini-2.5-pro", "gemini-3.1-pro-preview"])
    assert best == "gemini-3.1-pro-preview"


def test_select_best_prefers_gemini31_pro_for_file_task_when_available():
    manager = ModelManager(client=None)
    manager._cached_caps = {
        "gemini-3.1-pro-preview": _caps(speed=9, quality=10, reasoning=10, context=10, tier=10),
        "gemini-2.5-flash": _caps(speed=9, quality=7, reasoning=7, context=7, tier=7),
        "gemini-2.5-pro": _caps(speed=4, quality=10, reasoning=10, context=10, tier=9),
        "gemini-3-flash-preview": _caps(speed=10, quality=8, reasoning=8, context=8, tier=8),
    }

    best = manager._select_best(
        "FILE_TASK",
        ["gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview"],
    )
    assert best == "gemini-3.1-pro-preview"


def test_static_default_map_includes_file_task_route():
    manager = ModelManager(client=None)
    assert manager._static_default_map()["FILE_TASK"] == "deepseek-v4-pro"
    assert manager._static_default_map()["CHAT"] == "deepseek-v4-pro"
    assert manager._static_default_map()["VISION"] == "gemini-3-flash-preview"
