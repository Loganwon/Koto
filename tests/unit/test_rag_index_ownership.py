from __future__ import annotations

from types import SimpleNamespace


def _disable_embeddings(monkeypatch):
    import app.core.services.rag_service as rag_module

    def unavailable(*_args, **_kwargs):
        raise rag_module.EmbeddingBackendUnavailable("disabled in test")

    monkeypatch.setattr(rag_module, "_get_embeddings", unavailable)
    return rag_module


def test_index_file_replaces_existing_chunks_for_same_source(tmp_path, monkeypatch):
    rag_module = _disable_embeddings(monkeypatch)
    source = tmp_path / "note.txt"
    source.write_text("old unique content", encoding="utf-8")
    service = rag_module.RAGService(index_dir=str(tmp_path / "index"), auto_load=False)

    assert service.index_file(str(source)) == 1
    source.write_text("new replacement content", encoding="utf-8")
    assert service.index_file(str(source)) == 1

    assert service.stats()["doc_count"] == 1
    assert service.retrieve("old unique", k=5) == []
    assert service.retrieve("new replacement", k=5)[0]["source"] == str(source)


def test_remove_source_updates_lexical_index_and_persistence(tmp_path, monkeypatch):
    rag_module = _disable_embeddings(monkeypatch)
    index_dir = tmp_path / "index"
    service = rag_module.RAGService(index_dir=str(index_dir), auto_load=False)
    service.index_text("keep this content", source="keep.txt")
    service.index_text("delete this content", source="delete.txt")

    assert service.remove_source("delete.txt") == 1
    assert service.stats()["doc_count"] == 1
    assert service.retrieve("delete", k=5) == []

    restored = rag_module.RAGService(index_dir=str(index_dir), auto_load=True)
    assert restored.retrieve("delete", k=5) == []
    assert restored.retrieve("keep content", k=5)[0]["source"] == "keep.txt"


def test_file_indexer_removes_deleted_source_from_rag(tmp_path):
    from app.core.services.file_rag_indexer import FileRAGIndexer

    deleted_path = str((tmp_path / "deleted.txt").resolve())
    state_file = tmp_path / "state.json"
    indexer = FileRAGIndexer(
        watch_dir=str(tmp_path),
        index_dir=str(tmp_path / "index"),
        state_file=str(state_file),
    )
    removed_sources = []
    indexer._rag = SimpleNamespace(
        remove_source=lambda source: removed_sources.append(source),
    )
    indexer._state = {deleted_path: "hash"}

    assert indexer.remove_deleted() == 1
    assert removed_sources == [deleted_path]
    assert indexer.get_indexed_files() == []


def test_file_qa_uses_canonical_rag_sources(tmp_path, monkeypatch):
    from app.core.services import rag_service as rag_module
    from web.files.file_qa import _search_files_in_dirs

    matching = tmp_path / "matching.txt"
    matching.write_text("indexed content", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside content", encoding="utf-8")
    fake_rag = SimpleNamespace(
        hybrid_retrieve=lambda *_args, **_kwargs: [
            {"source": str(outside)},
            {"source": str(matching)},
        ]
    )
    monkeypatch.setattr(rag_module, "get_rag_service", lambda: fake_rag)

    assert _search_files_in_dirs(["indexed"], [str(tmp_path)]) == [str(matching)]
