from __future__ import annotations


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


def test_skill_injection_can_be_disabled_without_touching_skill_manager():
    from web.services.chat_stream.orchestrator import (
        _inject_skills_for_stream,
        _request_allows_skill_injection,
    )

    logger = _Logger()

    assert _request_allows_skill_injection({}) is True
    assert _request_allows_skill_injection({"skills_enabled": False}) is False
    assert _request_allows_skill_injection({"enable_skills": "off"}) is False
    assert _request_allows_skill_injection({"skill_mode": "detached"}) is False
    assert (
        _inject_skills_for_stream(
            "base instruction",
            "CHAT",
            "hello",
            {"skills_enabled": False},
            logger,
        )
        == "base instruction"
    )
    assert logger.warning_messages == []
