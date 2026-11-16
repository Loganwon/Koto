"""Bootstrap the unified tool registry for application startup.

Discovers and registers all tool sources:
  - Built-in Koto plugins (app.core.agent.toolkits.builtin)
  - Foundation office tools (app.core.agent.toolkits.foundation)
  - (future) MCP server tools
  - (future) External plugin contributions

Usage:
    from app.core.toolkits.bootstrap import bootstrap_tool_registry
    registry = bootstrap_tool_registry()
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from app.core.toolkits.unified_tool_registry import ToolSource, UnifiedToolRegistry


def bootstrap_tool_registry() -> UnifiedToolRegistry:
    """Create and populate the unified tool registry.

    Returns a fully initialized projection registry for MCP publication and
    diagnostics. Kernel Agent execution continues to use its canonical catalog.
    """
    registry = UnifiedToolRegistry()
    _load_builtin_plugins(registry)
    _load_foundation_tools(registry)
    registry.seal()
    logger.info(
        "[ToolBootstrap] registry ready: %d tools across %s",
        registry.tool_count(),
        ", ".join(
            f"{src.value}={len(registry.list_by_source(src))}"
            for src in ToolSource
            if registry.list_by_source(src)
        ),
    )
    return registry


def _load_builtin_plugins(registry: UnifiedToolRegistry) -> int:
    """Project the Kernel's canonical built-in profile without rescanning it."""
    try:
        from app.core.agent.tool_profiles import build_tool_registry
    except ImportError as exc:
        logger.warning("[ToolBootstrap] canonical profile unavailable: %s", exc)
        return 0

    try:
        kernel_registry, _report = build_tool_registry(profile_name="core")
    except Exception as exc:
        logger.warning("[ToolBootstrap] canonical profile failed: %s", exc)
        return 0
    total = 0
    for tool_name in kernel_registry.catalog.names():
        spec = kernel_registry.catalog.require(tool_name)
        # Public MCP projections cannot inject the trusted per-task host scope.
        # Context-bound tools remain callable only through the Kernel executor.
        if spec.requires_invocation_context:
            continue
        registry.register(
            name=f"builtin__{tool_name}",
            description=spec.description,
            source=ToolSource.BUILTIN,
            source_name=spec.source,
            handler=spec.handler,
            parameters=dict(spec.input_schema),
            read_only=bool(spec.read_only),
            timeout_seconds=spec.timeout_seconds,
            metadata={"version": spec.version},
        )
        total += 1

    logger.info("[ToolBootstrap] registered %d builtin tools", total)
    return total


def _load_foundation_tools(registry: UnifiedToolRegistry) -> int:
    """Register foundation office-format tools."""
    try:
        from app.core.agent.task_tools import TaskToolsPlugin
        from app.core.agent.toolkits.foundation.catalog import file_task_tool_specs
    except ImportError as exc:
        logger.warning("[ToolBootstrap] foundation imports failed: %s", exc)
        return 0

    try:
        tool_defs = TaskToolsPlugin().get_tools()
    except Exception as exc:
        logger.warning("[ToolBootstrap] foundation tool defs failed: %s", exc)
        return 0

    safety_by_name = {spec.name: spec for spec in file_task_tool_specs()}
    total = 0
    for tool in tool_defs:
        tool_name = tool.get("name", "")
        if not tool_name:
            continue
        try:
            registry.register(
                name=f"foundation__{tool_name}",
                description=str(tool.get("description", "")),
                source=ToolSource.FOUNDATION,
                source_name="foundation",
                handler=tool.get("func"),
                parameters=tool.get("parameters"),
                read_only=bool(
                    safety_by_name.get(tool_name)
                    and safety_by_name[tool_name].read_only
                ),
            )
            total += 1
        except Exception as exc:
            logger.warning(
                "[ToolBootstrap] failed to register foundation %s: %s",
                tool_name,
                exc,
            )

    logger.info("[ToolBootstrap] registered %d foundation tools", total)
    return total
