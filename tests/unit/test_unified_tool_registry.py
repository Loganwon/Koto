from __future__ import annotations

from pathlib import Path

from app.core.mcp.server import MCPServer
from app.core.toolkits.bootstrap import bootstrap_tool_registry
from app.core.toolkits.unified_tool_registry import (
    ToolSource,
    UnifiedToolRegistry,
    get_unified_tool_registry,
    reset_unified_tool_registry,
)


def test_bootstrap_projects_canonical_kernel_and_foundation_tools() -> None:
    registry = bootstrap_tool_registry()

    assert len(registry.list_by_source(ToolSource.BUILTIN)) == 34
    assert len(registry.list_by_source(ToolSource.FOUNDATION)) == 30
    assert registry.tool_count() == 64
    assert registry.get("builtin__get_current_time").handler is not None
    assert registry.get("foundation__read_docx_content").handler is not None
    assert registry.get("foundation__read_docx_content").read_only is True
    assert registry.get("foundation__write_docx_content").read_only is False
    assert not registry.has_tool("builtin__ui_read_context")
    assert not registry.has_tool("builtin__ui_apply_edit")
    assert not registry.has_tool("builtin__ui_save")
    assert registry.is_sealed is True
    assert not hasattr(registry, "call_tool")


def test_singleton_bootstrap_matches_explicit_bootstrap() -> None:
    reset_unified_tool_registry()
    try:
        registry = get_unified_tool_registry()
        assert registry.tool_count() == 64
        assert registry.has_tool("foundation__verify_task_completion")
    finally:
        reset_unified_tool_registry()


def test_tool_record_normalizes_koto_schema_types() -> None:
    registry = UnifiedToolRegistry()
    record = registry.register_foundation(
        "probe",
        "Schema probe",
        handler=lambda values: values,
        parameters={
            "type": "OBJECT",
            "properties": {"values": {"type": "ARRAY", "items": {"type": "STRING"}}},
        },
    )

    assert record.parameters["type"] == "object"
    assert record.parameters["properties"]["values"]["type"] == "array"
    assert record.parameters["properties"]["values"]["items"]["type"] == "string"


def test_replacing_cross_source_tool_removes_stale_source_index() -> None:
    registry = UnifiedToolRegistry()
    registry.register("shared", "old", ToolSource.BUILTIN, handler=lambda: "old")
    registry.register("shared", "new", ToolSource.PLUGIN, handler=lambda: "new")

    assert registry.list_by_source(ToolSource.BUILTIN) == []
    assert [record.name for record in registry.list_by_source(ToolSource.PLUGIN)] == [
        "shared"
    ]


def test_mcp_bootstrap_preserves_namespaces_and_safety_annotations() -> None:
    reset_unified_tool_registry()
    try:
        server = MCPServer()
        count = server.bootstrap_koto_tools()

        assert count == 64
        assert server.tool_registry.has_tool("builtin__get_current_time")
        assert server.tool_registry.has_tool("foundation__read_docx_content")
        assert server.tool_registry.has_tool("foundation__write_docx_content")
        read_tool = server.tool_registry.get("foundation__read_docx_content")
        write_tool = server.tool_registry.get("foundation__write_docx_content")
        assert read_tool.annotations["readOnlyHint"] is True
        assert write_tool.annotations["readOnlyHint"] is False
    finally:
        reset_unified_tool_registry()


def test_parallel_agent_tool_execution_layers_stay_removed() -> None:
    root = Path(__file__).resolve().parents[2]
    retired = (
        "app/core/toolkits/agent_tool_bridge.py",
        "app/core/toolkits/bridge.py",
        "app/core/toolkits/tool_executor.py",
    )

    assert all(not (root / relative).exists() for relative in retired)
