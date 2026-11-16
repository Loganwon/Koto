# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""KotoBrain implementation (reconstructed)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainRuntimeServices:
    """Application-owned dependencies for the non-streaming chat boundary."""

    select_model_for_task: Callable[..., str]
    get_utils: Callable[[], Any]
    get_local_executor: Callable[[], Any]
    get_workspace_dir: Callable[[], str]
    get_settings_manager: Callable[[], Any]
    get_model_map: Callable[[], dict]
    get_llm_gateway: Optional[Callable[[], Any]] = None


_default_brain_runtime: Optional[BrainRuntimeServices] = None


def configure_default_brain_runtime(runtime: BrainRuntimeServices) -> None:
    """Configure the web-owned default without creating a Core → Web import."""
    global _default_brain_runtime
    _default_brain_runtime = runtime


class KotoBrain:
    """Core chat brain with explicit routing, system execution, and generation."""

    def __init__(self, runtime: Optional[BrainRuntimeServices] = None) -> None:
        self._runtime = runtime or _default_brain_runtime

    def _services(self) -> BrainRuntimeServices:
        if self._runtime is None:
            raise RuntimeError(
                "Koto runtime services are not configured; pass BrainRuntimeServices."
            )
        return self._runtime

    def chat(
        self,
        history: List[Dict[str, str]],
        user_input: str,
        file_data: Optional[Any] = None,
        model: str = "auto",
        auto_model: bool = True,
        task_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        started = time.monotonic()
        services = self._services()
        target_key = str(task_type or "CHAT").strip().upper() or "CHAT"
        route_method = "Manual select" if task_type else "Stable chat boundary"

        resolved_model = str(model or "").strip()
        if auto_model or resolved_model in {"", "auto", "cloud"}:
            resolved_model = str(
                services.select_model_for_task(
                    target_key,
                    has_image=bool(
                        file_data
                        and str(file_data.get("mime_type") or "").startswith("image/")
                    ),
                )
                or "deepseek-chat"
            )

        result: Dict[str, Any] = {
            "task": target_key,
            "model": resolved_model,
            "route_method": route_method,
            "response": "",
            "images": [],
            "saved_files": [],
        }

        if target_key == "SYSTEM":
            execution = services.get_local_executor().execute(user_input)
            result["response"] = str(execution.get("message") or "")
            details = str(execution.get("details") or "").strip()
            if details:
                result["response"] += f"\n\n{details}"
            result["total_time"] = time.monotonic() - started
            return result

        gateway = services.get_llm_gateway() if services.get_llm_gateway else None
        if gateway is None:
            from app.core.llm.provider_factory import get_llm_provider

            gateway = get_llm_provider(model=resolved_model)

        messages = list(history) if history else []
        messages.append({"role": "user", "content": user_input})

        try:
            response = gateway.generate_content(
                model=resolved_model,
                contents=messages,
            )
            response_text = (
                response.text if hasattr(response, "text") else str(response)
            )
        except Exception as exc:
            logger.error("[KotoBrain] chat error: %s", exc)
            response_text = f"抱歉，处理请求时出现错误: {exc}"

        result["response"] = response_text
        result["total_time"] = time.monotonic() - started
        return result
