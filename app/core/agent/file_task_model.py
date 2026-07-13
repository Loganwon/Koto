from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from app.core.agent.file_task_contract import FileTaskRequest
from app.core.llm.model_mode import normalize_model_mode
from app.core.llm.model_selection import (
    get_configured_cloud_model,
    get_provider_for_model_mode,
)

logger = logging.getLogger(__name__)

_DEFAULT_FILE_TASK_MODEL = "deepseek-chat"
_FILE_TASK_LLM_CALL_TIMEOUT = float(os.getenv("KOTO_FILE_TASK_LLM_TIMEOUT", "45"))
# A local model has to load weights and execute on the user's hardware.  It
# therefore needs a separate budget from cloud requests; keeping this setting
# explicit makes slow hardware configurable without slowing cloud failures.
_LOCAL_FILE_TASK_LLM_CALL_TIMEOUT = float(
    os.getenv("KOTO_LOCAL_FILE_TASK_LLM_TIMEOUT", "180")
)
# File-task execution is iterative: it needs concise decisions and tool
# arguments, not a 4k-token essay on every turn.  Bounding one turn prevents a
# stalled local generation from monopolising Ollama and blocking the next task.
_LOCAL_FILE_TASK_MAX_OUTPUT_TOKENS = max(
    128, int(os.getenv("KOTO_LOCAL_FILE_TASK_MAX_OUTPUT_TOKENS", "1536"))
)


def _runtime_model_map() -> Dict[str, Any]:
    try:
        from web import runtime_context
    except Exception:
        return {}
    try:
        model_map = runtime_context.get_model_map()
    except Exception:
        return {}
    if isinstance(model_map, dict) and model_map:
        return model_map
    return {}


class FileTaskModelClient:
    """Small adapter for file-task model calls across cloud and local providers."""

    def __init__(
        self,
        *,
        api_key: str = "",
        default_model: str = "",
    ):
        self._api_key = api_key
        self._default_model = default_model or _DEFAULT_FILE_TASK_MODEL

    def call(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self._call_native(request=request, messages=messages, system=system, tools=tools)

    def _call_native(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        mode = normalize_model_mode(request.model_mode, default="deepseek")
        if mode == "local":
            return self._call_local(request=request, messages=messages, system=system, tools=tools)

        try:
            return self._call_cloud(request=request, messages=messages, system=system, tools=tools)
        except Exception as exc:
            if not bool(request.options.get("allow_local_fallback", True)):
                raise
            # API-layer errors (auth, quota, bad-request) should not trigger a
            # local fallback — the cloud is reachable but refusing the request.
            if self._is_api_layer_error(exc):
                raise
            if not self._is_local_available():
                raise
            logger.warning(
                "[FileTaskModelClient] cloud call failed (network/timeout), falling back to local model: %s",
                exc,
            )
            return self._call_local(request=request, messages=messages, system=system, tools=tools)

    @staticmethod
    def _is_api_layer_error(exc: Exception) -> bool:
        """Return True for errors that indicate the cloud API is reachable but
        refusing the request (e.g. invalid key, quota exceeded, bad request).
        These should NOT trigger a local-model fallback."""
        msg = str(exc).lower()
        api_signals = ("401", "403", "429", "invalid api key", "permission denied", "quota exceeded", "rate limit")
        return any(s in msg for s in api_signals)

    def _call_cloud(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from app.core.llm.provider_factory import get_llm_provider

        model_id = self._cloud_model_id(request)
        provider_name = get_provider_for_model_mode(request.model_mode)
        provider_kwargs = {"provider": provider_name, "model": model_id}
        provider = get_llm_provider(**provider_kwargs)
        try:
            from app.core.llm.model_fallback import get_fallback_executor

            executor = get_fallback_executor()
            return executor.generate_with_fallback(
                provider=provider,
                prompt=messages,
                preferred_model=model_id,
                task_type="FILE_TASK",
                system_instruction=system,
                tools=tools if tools else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
                temperature=0.2,
            )
        except ImportError:
            return provider.generate_content(
                prompt=messages,
                model=model_id,
                system_instruction=system,
                tools=tools if tools else None,
                stream=False,
                call_timeout=_FILE_TASK_LLM_CALL_TIMEOUT,
                temperature=0.2,
            )

    def _call_local(
        self,
        *,
        request: FileTaskRequest,
        messages: List[Dict[str, Any]],
        system: str,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self._is_local_available():
            raise RuntimeError("Local Ollama is not reachable")
        from app.core.llm.ollama_llm_provider import OllamaLLMProvider

        model_id = self._local_model_id(request)
        self._ensure_local_tool_support(model_id, tools)
        logger.info(
            "[FileTaskModelClient] local file-task call model=%s messages=%d tools=%d timeout=%.1fs",
            model_id or "<auto>",
            len(messages),
            len(tools or []),
            _LOCAL_FILE_TASK_LLM_CALL_TIMEOUT,
        )
        provider = OllamaLLMProvider(model=model_id or None)
        return provider.generate_content(
            prompt=messages,
            model=model_id or None,
            system_instruction=system,
            tools=tools if tools else None,
            stream=False,
            call_timeout=_LOCAL_FILE_TASK_LLM_CALL_TIMEOUT,
            temperature=0.2,
            think=False,
            num_predict=_LOCAL_FILE_TASK_MAX_OUTPUT_TOKENS,
        )

    @staticmethod
    def _ensure_local_tool_support(model_id: str, tools: List[Dict[str, Any]]) -> None:
        """Fail before the task stream starts when Ollama says tools are unsupported."""
        if not tools:
            return
        resolved_model = str(model_id or "").strip()
        if not resolved_model:
            try:
                from app.core.llm.local_model_runtime import get_configured_local_model_tag

                resolved_model = str(get_configured_local_model_tag() or "").strip()
            except Exception:
                return
        if not resolved_model:
            return
        try:
            from app.core.llm.local_model_capabilities import local_model_supports_tools

            supports_tools = local_model_supports_tools(resolved_model)
        except Exception:
            return
        if supports_tools is False:
            raise RuntimeError(
                f"本地模型 {resolved_model} 不支持工具调用，无法执行文件任务。"
                "请在设置中选择支持 tools 的模型（例如 qwen3.5:9b）。"
            )

    def _cloud_model_id(self, request: FileTaskRequest) -> str:
        requested = str(request.model_id or "").strip()
        mode = normalize_model_mode(request.model_mode, default="deepseek")
        provider = get_provider_for_model_mode(mode)
        ignored = {"auto", "cloud", "local", "deepseek", "ollama"}
        if requested and requested.lower() not in ignored:
            return requested
        model_map = _runtime_model_map()
        for task_key in ("FILE_TASK", "CHAT"):
            model_from_app = str(model_map.get(task_key) or "").strip()
            if model_from_app:
                return model_from_app
        return get_configured_cloud_model(
            task_type="FILE_TASK",
            fallback_model=self._default_model,
            provider=provider,
        )

    def _local_model_id(self, request: FileTaskRequest) -> str:
        configured = str(request.options.get("local_model") or request.model_id or "").strip()
        if configured.lower() in {"auto", "cloud", "local", "deepseek", "ollama"}:
            return ""
        return configured

    def _is_local_available(self) -> bool:
        try:
            from app.core.shared.llm_helpers import is_ollama_alive

            return bool(is_ollama_alive())
        except Exception:
            return False
