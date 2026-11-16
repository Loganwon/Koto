# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Deterministic construction of Koto agents and their tool profiles."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def _resolve_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """Read the configured DeepSeek key without mutating process state."""
    return (
        api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY")
    )


def _build_registry(
    api_key: Optional[str] = None,
    *,
    profile: str = "core",
    addon_tool_names=(),
) -> "ToolRegistry":
    """Build a registry from one explicit, declarative tool profile.

    The production surface is fixed built-ins plus explicitly admitted Addons.
    MCP servers and user scripts remain separate subsystems and cannot be
    injected through this factory.
    """
    from app.core.agent.tool_profiles import build_tool_registry

    registry, report = build_tool_registry(
        profile_name=profile,
        api_key=api_key,
        addon_tool_names=addon_tool_names,
    )
    logger.info(
        "[agent.factory] tool profile=%s tools=%s builtins=%s skipped=%s",
        report.profile,
        report.tool_count,
        len(report.loaded_builtins),
        sorted(report.skipped_sources),
    )
    return registry


def _configure_output_validator(llm_provider, provider_name: str) -> None:
    try:
        from app.core.llm.model_selection import get_configured_cloud_model
        from app.core.security.output_validator import OutputValidator

        OutputValidator.configure_llm_judge(
            client=llm_provider,
            model_id=get_configured_cloud_model(
                task_type="CHAT",
                fallback_model="deepseek-chat",
                provider=provider_name,
            ),
            timeout=15.0,
        )
    except Exception as exc:
        logger.debug("[agent.factory] output validator judge skipped: %s", exc)


def create_agent(
    api_key: Optional[str] = None,
    model_id: Optional[str] = None,
    *,
    tool_profile: str = "core",
    addon_tool_names=(),
):
    """Create Koto's deterministic production Agent.

    Installed optional packages never change the runtime type. Specialized
    graph workflows live behind ``WorkflowEngine`` rather than another general
    Agent implementation.
    """
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.llm.model_selection import (
        get_configured_cloud_model,
        get_configured_cloud_provider,
    )
    from app.core.llm.provider_factory import get_llm_provider

    usage_api_key = _resolve_api_key(api_key)
    provider_name = get_configured_cloud_provider()
    active_model_id = str(model_id or "").strip() or get_configured_cloud_model(
        task_type="AGENT",
        fallback_model="deepseek-chat",
        provider=provider_name,
    )
    if provider_name == "deepseek" and not usage_api_key:
        logger.warning("No API Key provided for Agent. Agent may fail at generation.")

    registry = _build_registry(
        api_key=usage_api_key,
        profile=tool_profile,
        addon_tool_names=addon_tool_names,
    )
    llm_provider = get_llm_provider(
        provider=provider_name,
        model=active_model_id,
        allow_local_fallback=False,
    )
    _configure_output_validator(llm_provider, provider_name)

    logger.info(
        "[agent.factory] runtime=kernel provider=%s model=%s profile=%s",
        provider_name,
        active_model_id,
        tool_profile,
    )
    return KernelAgent(
        llm_provider=llm_provider,
        tool_registry=registry,
        model_id=active_model_id,
        use_tool_router=True,
        tool_router_max=20,
    )


def create_local_agent(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    tool_profile: str = "core",
    addon_tool_names=(),
) -> "KernelAgent":
    """Create the same production Agent loop backed by local Ollama."""
    from app.core.agent.kernel_agent import KernelAgent
    from app.core.llm.ollama_llm_provider import OllamaLLMProvider

    if not model:
        try:
            from app.core.llm.local_model_runtime import get_configured_local_model_tag

            model = get_configured_local_model_tag() or None
        except Exception:
            model = None

    llm_kwargs = {"base_url": base_url} if base_url else {}
    llm_provider = OllamaLLMProvider(model=model, **llm_kwargs)
    registry = _build_registry(
        profile=tool_profile,
        addon_tool_names=addon_tool_names,
    )
    logger.info(
        "[agent.factory] runtime=kernel-local model=%s profile=%s",
        model,
        tool_profile,
    )
    return KernelAgent(
        llm_provider=llm_provider,
        tool_registry=registry,
        model_id=model,
        use_tool_router=True,
        tool_router_max=15,
    )


__all__ = [
    "create_agent",
    "create_local_agent",
]
