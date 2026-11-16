from __future__ import annotations

from types import SimpleNamespace


class _Logger:
    def __init__(self) -> None:
        self.debug_messages: list[str] = []
        self.warning_messages: list[str] = []

    def debug(self, message, *args) -> None:
        self.debug_messages.append(str(message))

    def warning(self, message, *args) -> None:
        self.warning_messages.append(str(message))


def test_workspace_file_context_block_includes_selection_metadata():
    from web.services.chat_stream.orchestrator import _workspace_file_context_block

    block = _workspace_file_context_block(
        {
            "file_path": "workspace/report.xlsx",
            "file_type": "xlsx",
            "open_tabs": ["report.xlsx", "notes.md"],
            "selection": "A\t10\nB\t20",
            "selection_kind": "xlsx",
            "selection_source": "sheet",
            "selection_meta": {"sheetName": "Sales", "rangeA1": "A1:B2"},
            "attached_files": [{"path": "workspace/input.csv"}],
        }
    )

    assert "## 文件助手上下文" in block
    assert "当前打开文件: workspace/report.xlsx (类型: xlsx)" in block
    assert "工作区打开的标签页: report.xlsx, notes.md" in block
    assert "选区类型: xlsx" in block
    assert "选区元信息: sheetName=Sales, rangeA1=A1:B2" in block
    assert "用户明确选中的内容:\nA\t10\nB\t20" in block
    assert "已附加分析文件: workspace/input.csv" in block


def test_stream_orchestrator_has_no_legacy_skill_injection_path():
    from pathlib import Path

    source = Path("web/services/chat_stream/orchestrator.py").read_text(
        encoding="utf-8"
    )
    assert "_inject_skills_for_stream" not in source
    assert "_request_allows_skill_injection" not in source
    assert "app.core.skills" not in source
    assert "_addon_runtime_plan" in source


def _prepared_context(monkeypatch, **data):
    from app.core.agent import addons
    from app.core.llm import provider_factory
    from app.core.memory.context_window_manager import ContextWindowManager
    from app.core.services import rag_service
    from app.core.services.graph_rag_service import GraphRAGService
    from web.services.chat_stream import orchestrator

    plan = SimpleNamespace(tool_names=(), retriever_names=(), to_dict=lambda: {})
    monkeypatch.setattr(
        addons, "get_addon_runtime", lambda: SimpleNamespace(plan=lambda _request: plan)
    )
    monkeypatch.setattr(
        ContextWindowManager,
        "manage",
        lambda **kwargs: {
            "history": [{"role": "user", "content": "bounded history"}],
            "paged_in_context": "memory-evidence",
        },
    )
    monkeypatch.setattr(
        rag_service,
        "get_rag_service",
        lambda: SimpleNamespace(
            stats=lambda: {"initialized": True},
            hybrid_retrieve=lambda *_args, **_kwargs: [
                {"source": "evidence.md", "content": "rag-evidence", "score": 0.9}
            ],
        ),
    )
    monkeypatch.setattr(
        GraphRAGService, "retrieve", lambda *_args, **_kwargs: "graph-evidence"
    )
    monkeypatch.setattr(provider_factory, "is_local_mode", lambda: False)
    monkeypatch.setattr(provider_factory, "get_local_model_tag", lambda: "local-model")
    monkeypatch.setattr(
        orchestrator, "select_task_model", lambda *_args, **_kwargs: "routed-model"
    )
    request = SimpleNamespace(json={"session": "chat-a", "message": "分析选区", **data})
    sessions = SimpleNamespace(load=lambda _name: [], load_full=lambda _name: [])
    logger = SimpleNamespace(
        debug=lambda *_args: None, warning=lambda *_args: None, info=lambda *_args: None
    )
    return orchestrator.setup_chat_stream_context(
        request=request,
        session_manager=sessions,
        settings_manager=SimpleNamespace(get=lambda *_args: False),
        _app_logger=logger,
        _interrupt_manager=None,
        Utils=SimpleNamespace(sanitize_string=lambda text: text),
        get_memory_manager=lambda: None,
        WebSearcher=None,
        _get_chat_system_instruction=lambda _query: "stable-chat-persona",
        _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION=lambda: "stable-chat-persona",
        _get_writing_style_instruction=lambda _query: "\nstyle-evidence",
        _TASK_SYSTEM_ADDENDUMS={},
        MODEL_MAP={},
        _resolve_requested_model_id=lambda requested, **_kwargs: requested,
        get_model_display_name=lambda model: model,
        API_KEY="offline-test-key",
    )["context"]


def test_default_agent_keeps_dynamic_context_without_duplicate_chat_instruction(
    monkeypatch,
):
    context = _prepared_context(
        monkeypatch,
        file_context={
            "file_path": "workspace/report.xlsx",
            "file_type": "xlsx",
            "selection": "A\t10",
            "selection_meta": {"sheetName": "Q1", "rangeA1": "A1:B1"},
        },
    )
    assert context["task_type"] == "AGENT"
    dynamic = context["agent_system_context"]
    assert "stable-chat-persona" not in dynamic
    for evidence in (
        "workspace/report.xlsx",
        "A\t10",
        "rangeA1=A1:B1",
        "rag-evidence",
        "graph-evidence",
        "memory-evidence",
        "style-evidence",
    ):
        assert dynamic.count(evidence) == 1
    assert context["history"] == [{"role": "user", "content": "bounded history"}]


def test_agent_model_selection_keeps_explicit_choice_and_local_mode(monkeypatch):
    explicit = _prepared_context(monkeypatch, locked_model="deepseek-reasoner")
    assert explicit["model_id"] == "deepseek-reasoner"
    assert explicit["locked_model"] == "deepseek-reasoner"
    local = _prepared_context(monkeypatch, locked_model="local")
    assert local["model_id"] == "local-model"
    assert local["locked_model"] == "local"


def test_agent_preserves_explicit_task_and_browser_scope(monkeypatch):
    context = _prepared_context(
        monkeypatch,
        locked_task="WEB_SEARCH",
        frontend_session_id="browser-a",
        file_context={
            "file_path": "workspace/report.docx",
            "file_id": "file-a",
        },
    )
    assert context["task_type"] == "WEB_SEARCH"
    assert context["frontend_scope"] == {
        "frontend_session_id": "browser-a",
        "document_path": "workspace/report.docx",
        "file_id": "file-a",
    }
