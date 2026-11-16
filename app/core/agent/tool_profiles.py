"""Declarative tool profiles for Koto agents.

This module is the only place that composes the Agent tool surface.  Runtime
code selects a named profile instead of importing extensions or silently
expanding the model's tools. Addons and MCP servers are opt-in extension sources.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltinToolDescriptor:
    builtin_id: str
    module: str
    class_name: str
    required: bool = False
    takes_api_key: bool = False
    allowed_tools: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class ToolProfile:
    name: str
    builtins: Tuple[BuiltinToolDescriptor, ...]
    include_addons: bool = False


@dataclass
class RegistryBuildReport:
    profile: str
    loaded_builtins: list[str] = field(default_factory=list)
    skipped_sources: Dict[str, str] = field(default_factory=dict)
    contributor_tool_counts: Dict[str, int] = field(default_factory=dict)
    tool_count: int = 0

    def public_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "loaded_builtins": list(self.loaded_builtins),
            "skipped_sources": dict(self.skipped_sources),
            "contributor_tool_counts": dict(self.contributor_tool_counts),
            "tool_count": self.tool_count,
        }


_CORE_BUILTINS = (
    BuiltinToolDescriptor(
        "document_ui",
        "app.core.agent.toolkits.builtin.document_ui_plugin",
        "DocumentUIPlugin",
        required=True,
        allowed_tools=(
            "ui_read_context",
            "ui_action_status",
            "ui_apply_edit",
            "ui_save",
        ),
    ),
    BuiltinToolDescriptor(
        "basic",
        "app.core.agent.toolkits.builtin.basic_tools_plugin",
        "BasicToolsPlugin",
        required=True,
        allowed_tools=("get_current_time", "calculate"),
    ),
    BuiltinToolDescriptor(
        "file_editor",
        "app.core.agent.toolkits.builtin.file_editor_plugin",
        "FileEditorPlugin",
        required=True,
        allowed_tools=(
            "read_file",
            "replace_text",
            "patch_file",
            "insert_line",
            "delete_lines",
            "append_text",
            "write_file",
            "delete_file",
            "copy_file",
            "move_file",
            "rename_file",
            "create_directory",
            "get_file_info",
            "list_directory",
            "find_file",
            "list_backups",
            "restore_backup",
        ),
    ),
    BuiltinToolDescriptor(
        "web_search",
        "app.core.agent.toolkits.builtin.search_plugin",
        "SearchPlugin",
        required=True,
        takes_api_key=True,
        allowed_tools=("web_search",),
    ),
    BuiltinToolDescriptor(
        "system_tools",
        "app.core.agent.toolkits.builtin.system_tools_plugin",
        "SystemToolsPlugin",
        required=True,
        allowed_tools=("python_exec", "pip_check"),
    ),
    BuiltinToolDescriptor(
        "system_info",
        "app.core.agent.toolkits.builtin.system_info_plugin",
        "SystemInfoPlugin",
        required=True,
        allowed_tools=(
            "query_cpu_status",
            "query_memory_status",
            "query_disk_usage",
            "query_network_status",
            "query_python_env",
            "list_running_apps",
            "get_system_warnings",
        ),
    ),
    BuiltinToolDescriptor(
        "memory",
        "app.core.agent.toolkits.builtin.memory_tools_plugin",
        "MemoryToolsPlugin",
        allowed_tools=("memory_search", "memory_save", "context_recall"),
    ),
    BuiltinToolDescriptor(
        "productivity",
        "app.core.agent.toolkits.builtin.productivity_plugin",
        "ProductivityPlugin",
        allowed_tools=("list_directory", "get_clipboard_text", "set_clipboard_text"),
    ),
)

_PROFILES: Mapping[str, ToolProfile] = {
    # Stable default: fixed Koto tools plus explicitly admitted Add-ons.
    # External MCP servers are configured at runtime and never change the
    # agent tool surface.
    "core": ToolProfile(
        name="core",
        builtins=_CORE_BUILTINS,
        include_addons=True,
    ),
}


def get_tool_profile(name: str) -> ToolProfile:
    normalized = str(name or "").strip().lower()
    try:
        return _PROFILES[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(_PROFILES))
        raise ValueError(
            f"unknown tool profile '{name}'; expected one of: {supported}"
        ) from exc


def profile_names() -> Tuple[str, ...]:
    return tuple(_PROFILES)


def build_tool_registry(
    *,
    profile_name: str,
    api_key: Optional[str] = None,
    addon_tool_names: Iterable[str] = (),
):
    from app.core.agent.tool_registry import ToolRegistry

    profile = get_tool_profile(profile_name)
    registry = ToolRegistry()
    report = RegistryBuildReport(profile=profile.name)

    for descriptor in profile.builtins:
        try:
            module = importlib.import_module(descriptor.module)
            builtin_class = getattr(module, descriptor.class_name)
            kwargs = {"api_key": api_key} if descriptor.takes_api_key else {}
            registry.register_plugin(
                builtin_class(**kwargs),
                tool_allowlist=descriptor.allowed_tools,
            )
            report.loaded_builtins.append(descriptor.builtin_id)
        except Exception as exc:
            if descriptor.required:
                raise RuntimeError(
                    f"required built-in '{descriptor.builtin_id}' failed to load: {exc}"
                ) from exc
            report.skipped_sources[descriptor.builtin_id] = str(exc)
            logger.warning(
                "[tool_profiles] optional built-in %s skipped: %s",
                descriptor.builtin_id,
                exc,
            )

    if profile.include_addons:
        _load_addon_tools(registry, report, addon_tool_names)

    report.tool_count = len(registry.get_definitions())
    # Compatibility/debugging hook. New code should consume the report returned
    # by this function instead of reaching into the registry.
    registry._build_report = report
    return registry, report


def _load_addon_tools(
    registry: Any,
    report: RegistryBuildReport,
    names: Iterable[str],
) -> None:
    try:
        from app.core.agent.addons import get_addon_runtime

        planned_names = tuple(
            dict.fromkeys(str(name).strip() for name in names if str(name).strip())
        )
        specs = get_addon_runtime().tool_specs(planned_names) if planned_names else ()
        registry.register_specs(specs)
        if specs:
            report.contributor_tool_counts["addons"] = len(specs)
    except Exception as exc:
        report.skipped_sources["addons"] = str(exc)
        logger.warning("[tool_profiles] Add-on tools skipped: %s", exc)


__all__ = [
    "BuiltinToolDescriptor",
    "RegistryBuildReport",
    "ToolProfile",
    "build_tool_registry",
    "get_tool_profile",
    "profile_names",
]
