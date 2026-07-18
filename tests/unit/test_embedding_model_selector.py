from __future__ import annotations

from pathlib import Path

from app.core.llm import embedding_model_selector as selector


def test_resolve_gemini_embedding_model_prefers_supported_stable_model(monkeypatch):
    selector.resolve_gemini_embedding_model.cache_clear()
    monkeypatch.delenv("KOTO_GEMINI_EMBEDDING_MODEL", raising=False)
    monkeypatch.setattr(
        selector,
        "_iter_embed_models",
        lambda api_key: (
            "models/gemini-embedding-001",
            "models/gemini-embedding-2",
        ),
    )

    resolved = selector.resolve_gemini_embedding_model("test-key")

    assert resolved == "models/gemini-embedding-2"


def test_resolve_gemini_embedding_model_uses_env_override_when_supported(monkeypatch):
    selector.resolve_gemini_embedding_model.cache_clear()
    monkeypatch.setenv("KOTO_GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setattr(
        selector,
        "_iter_embed_models",
        lambda api_key: ("models/gemini-embedding-001",),
    )

    resolved = selector.resolve_gemini_embedding_model("test-key")

    assert resolved == "models/gemini-embedding-001"


def test_runtime_embedding_paths_are_local_only():
    root = Path(__file__).resolve().parents[2]
    rag_service = (root / "app" / "core" / "services" / "rag_service.py").read_text(
        encoding="utf-8"
    )
    knowledge_base = (
        root / "app" / "core" / "services" / "knowledge_base.py"
    ).read_text(encoding="utf-8")
    web_app = (root / "web" / "app.py").read_text(encoding="utf-8")

    assert 'model="models/text-embedding-004"' not in rag_service
    assert 'self.embedding_model = "text-embedding-004"' not in knowledge_base
    assert 'model="text-embedding-004", contents=safe_texts' not in web_app
    assert "resolve_gemini_embedding_model" not in rag_service
    assert "GoogleGenerativeAIEmbeddings" not in rag_service
    assert 'model_name="BAAI/bge-m3"' in rag_service
    assert "_OllamaLocalEmbeddings" in rag_service
