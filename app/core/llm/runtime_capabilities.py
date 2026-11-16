# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Non-blocking runtime capability state for optional AI providers.

The desktop shell, file browser, and settings UI are useful without an AI
provider.  This module keeps provider readiness separate from application
readiness and never loads model weights while inspecting local availability.
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import requests


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"
    INCOMPATIBLE = "incompatible"
    CHECKING = "checking"


@dataclass(frozen=True)
class CapabilityState:
    name: str
    status: CapabilityStatus
    reason: str = ""
    repair_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


class RuntimeCapabilityRegistry:
    """Thread-safe snapshot store shared by the launcher and HTTP layer."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, CapabilityState] = {}

    def set(self, state: CapabilityState) -> CapabilityState:
        with self._lock:
            self._states[state.name] = state
        return state

    def get(self, name: str) -> CapabilityState | None:
        with self._lock:
            return self._states.get(name)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: state.to_dict() for name, state in self._states.items()}


runtime_capabilities = RuntimeCapabilityRegistry()


def _ollama_base_url() -> str:
    return (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _configured_states() -> tuple[str, CapabilityState, CapabilityState]:
    from app.core.llm.deepseek_config import get_deepseek_api_key
    from app.core.llm.local_model_runtime import (
        get_configured_local_model_tag,
        get_configured_model_mode,
    )

    mode = get_configured_model_mode()
    cloud_key = get_deepseek_api_key()
    local_model = get_configured_local_model_tag()

    cloud = CapabilityState(
        name="cloud_model",
        status=(
            CapabilityStatus.AVAILABLE if cloud_key else CapabilityStatus.MISCONFIGURED
        ),
        reason="configured_unprobed" if cloud_key else "api_key_missing",
        repair_action="" if cloud_key else "open_model_settings",
        metadata={"provider": "deepseek", "network_probed": False},
    )
    local = CapabilityState(
        name="local_model",
        status=(
            CapabilityStatus.CHECKING if local_model else CapabilityStatus.MISCONFIGURED
        ),
        reason="configured_unprobed" if local_model else "model_not_selected",
        repair_action="check_local_runtime" if local_model else "select_local_model",
        metadata={
            "provider": "ollama",
            "model_id": local_model,
            "network_probed": False,
        },
    )
    return mode, cloud, local


def inspect_local_model_capability(*, timeout: float = 1.0) -> CapabilityState:
    """Inspect Ollama and its selected tag without invoking generation."""
    from app.core.llm.local_model_runtime import get_configured_local_model_tag

    model_id = get_configured_local_model_tag()
    base_url = _ollama_base_url()
    metadata: dict[str, Any] = {
        "provider": "ollama",
        "model_id": model_id,
        "base_url": base_url,
        "network_probed": True,
    }
    if not model_id:
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.MISCONFIGURED,
                reason="model_not_selected",
                repair_action="select_local_model",
                metadata=metadata,
            )
        )

    try:
        response = requests.get(
            f"{base_url}/api/tags",
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        models = (response.json() or {}).get("models") or []
    except (requests.RequestException, TypeError, ValueError) as exc:
        metadata["error_type"] = type(exc).__name__
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.UNAVAILABLE,
                reason="ollama_unreachable",
                repair_action="start_or_install_ollama",
                metadata=metadata,
            )
        )

    installed = {
        str(item.get("name") or item.get("model") or "").strip()
        for item in models
        if isinstance(item, dict)
    }
    if model_id not in installed:
        metadata["installed_count"] = len(installed)
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.MISCONFIGURED,
                reason="model_not_installed",
                repair_action="install_or_select_local_model",
                metadata=metadata,
            )
        )

    from app.core.llm.ollama_runtime_compat import inspect_ollama_model_compatibility

    compatibility = inspect_ollama_model_compatibility(
        model_id, base_url=base_url, timeout=timeout
    )
    metadata.update(
        {
            "current_version": compatibility.get("current_version", ""),
            "required_version": compatibility.get("required_version", ""),
        }
    )
    if compatibility.get("compatible") is False:
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.INCOMPATIBLE,
                reason="ollama_runtime_outdated",
                repair_action="update_ollama_or_switch_model",
                metadata=metadata,
            )
        )

    compatibility_reason = str(compatibility.get("reason") or "")
    if compatibility_reason == "model_not_installed":
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.MISCONFIGURED,
                reason="model_not_installed",
                repair_action="install_or_select_local_model",
                metadata=metadata,
            )
        )
    if compatibility_reason == "model_load_failed":
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.MISCONFIGURED,
                reason="model_load_failed",
                repair_action="reinstall_or_switch_local_model",
                metadata=metadata,
            )
        )
    if compatibility_reason in {"compatibility_probe_failed", "ollama_unreachable"}:
        return runtime_capabilities.set(
            CapabilityState(
                name="local_model",
                status=CapabilityStatus.UNAVAILABLE,
                reason=compatibility_reason,
                repair_action="check_local_runtime",
                metadata=metadata,
            )
        )

    return runtime_capabilities.set(
        CapabilityState(
            name="local_model",
            status=CapabilityStatus.AVAILABLE,
            reason=(
                "ready"
                if compatibility.get("compatible") is True
                else "ready_compatibility_unknown"
            ),
            metadata=metadata,
        )
    )


def refresh_model_capabilities(*, probe_local: bool = False) -> dict[str, Any]:
    """Refresh provider state; the default path performs no network I/O."""
    mode, cloud, local = _configured_states()
    runtime_capabilities.set(cloud)
    runtime_capabilities.set(local)
    if probe_local and local.metadata.get("model_id"):
        local = inspect_local_model_capability()

    selected = local if mode == "local" else cloud
    active = CapabilityState(
        name="active_model",
        status=selected.status,
        reason=selected.reason,
        repair_action=selected.repair_action,
        metadata={"mode": mode, **selected.metadata},
    )
    runtime_capabilities.set(active)
    return {"mode": mode, "capabilities": runtime_capabilities.snapshot()}


__all__ = [
    "CapabilityState",
    "CapabilityStatus",
    "RuntimeCapabilityRegistry",
    "inspect_local_model_capability",
    "refresh_model_capabilities",
    "runtime_capabilities",
]
