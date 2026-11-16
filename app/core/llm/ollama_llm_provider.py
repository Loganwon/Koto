# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
OllamaLLMProvider
=================
A LLMProvider implementation for Ollama used through KernelAgent's
ProviderModelGateway.

Prompt/context policy is owned by the Agent request adapter. This provider only
translates the normalized model request and must not inject extension behavior.

Tool calling
─────────────
Passed through using Ollama's native function-call format. Tool execution
requires a complete structured call and valid JSON arguments; plain assistant
text is never interpreted as a tool request.

Usage
─────
    from app.core.llm.ollama_llm_provider import OllamaLLMProvider
    from app.core.agent.kernel_agent import KernelAgent

    agent = KernelAgent(
        llm_provider=OllamaLLMProvider(model="qwen3:8b"),
        ...
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional, Union

from app.core.llm.base import LLMProvider
from app.core.llm.stream_control import watch_stream_cancellation

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def _supports_thinking_toggle(model_tag: str) -> bool:
    """Only send Ollama's ``think`` field to model families known to support it."""
    normalized = str(model_tag or "").strip().lower()
    return normalized.startswith("qwen3") or normalized.startswith("qwen-3")


# ─────────────────────────────────────────────────────────────────────────────
# Format helpers
# ─────────────────────────────────────────────────────────────────────────────


def _to_ollama_messages(
    prompt: Union[str, List[Dict[str, Any]]],
    system_instruction: Optional[str],
) -> List[Dict[str, Any]]:
    """Convert KernelAgent prompt + system_instruction → Ollama messages list."""
    messages: List[Dict[str, Any]] = []

    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    if isinstance(prompt, str):
        messages.append({"role": "user", "content": prompt})
        return messages

    for msg in prompt or []:
        role = msg.get("role", "user")
        if role == "model":
            role = "assistant"

        if role == "assistant":
            content = msg.get("content", "")
            if not content and isinstance(msg.get("parts"), list):
                content = " ".join(str(p) for p in msg["parts"] if p)
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                # Convert to Ollama OpenAI-compatible tool_calls format
                ollama_tcs = []
                for tc in tool_calls:
                    name, arguments = _tool_function(tc)
                    ollama_tcs.append(
                        {
                            "id": tc.get("id") or tc.get("call_id") or "",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or "",
                        "tool_calls": ollama_tcs,
                    }
                )
            elif content:
                messages.append({"role": "assistant", "content": str(content)})

        elif role in {"function", "tool"}:
            # Tool result — convert to Ollama "tool" role
            fn_name = msg.get("name") or msg.get("tool_name") or ""
            content = msg.get("content", "")
            tool_call_id = msg.get("tool_call_id") or ""
            if not tool_call_id:
                # Fallback: search backward for matching tool_call id
                for prev in reversed(messages):
                    if prev.get("role") == "assistant":
                        for tc in prev.get("tool_calls") or []:
                            if (tc.get("function") or {}).get("name") == fn_name:
                                tool_call_id = tc.get("id", "")
                                break
                    if tool_call_id:
                        break
            if not fn_name and tool_call_id:
                for prev in reversed(messages):
                    matching = next(
                        (
                            call
                            for call in prev.get("tool_calls", [])
                            if call.get("id") == tool_call_id
                        ),
                        None,
                    )
                    if matching:
                        fn_name = matching["function"]["name"]
                        break
            tool_message = {
                "role": "tool",
                "content": (
                    content
                    if isinstance(content, str)
                    else json.dumps(content, ensure_ascii=False)
                ),
            }
            if tool_call_id:
                tool_message["tool_call_id"] = tool_call_id
            if fn_name:
                tool_message.update({"name": fn_name, "tool_name": fn_name})
            messages.append(tool_message)

        elif role in {"user", "system", "developer"}:
            content = msg.get("content", "")
            if not content and isinstance(msg.get("parts"), list):
                content = " ".join(str(p) for p in msg["parts"] if p)
            if content:
                messages.append(
                    {
                        "role": "system" if role == "developer" else role,
                        "content": str(content),
                    }
                )

    return messages


def _tool_function(value: Dict[str, Any]):
    """Accept canonical and OpenAI shapes without dropping names or arguments."""
    function = value.get("function")
    function = function if isinstance(function, dict) else {}
    name = value.get("name") or function.get("name")
    if not name:
        raise ValueError("Ollama tool call requires a function name")
    arguments = value.get("args")
    if arguments is None:
        arguments = value.get("arguments")
    if arguments is None:
        arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict):
        raise ValueError("Ollama tool arguments must be a JSON object")
    return str(name), arguments


def _to_ollama_tools(tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """Convert KernelAgent tool defs → Ollama OpenAI-compatible tool format."""
    if not tools:
        return None
    result = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        function = t.get("function")
        declaration = function if isinstance(function, dict) else t
        if not declaration.get("name"):
            # Catalog conversion historically filters incomplete declarations.
            # Model-returned calls use _tool_function and still fail closed.
            continue
        result.append(
            {
                "type": "function",
                "function": {
                    "name": declaration["name"],
                    "description": declaration.get("description", ""),
                    "parameters": declaration.get("parameters")
                    or {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
        )
    return result or None


def _parse_ollama_response(resp_json: Dict) -> Dict[str, Any]:
    """Convert Ollama /api/chat response → Kernel model response format."""
    import re as _re
    import uuid as _uuid

    msg = resp_json.get("message") or {}
    content = msg.get("content") or ""
    # Strip <think>...</think> blocks (qwen3 thinking mode)
    content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()

    tool_calls: List[Dict] = []
    for tc in msg.get("tool_calls") or []:
        name, args = _tool_function(tc)
        # Native Ollama may omit ids, but the Kernel requires a stable pairing.
        tc_id = tc.get("id") or tc.get("call_id") or _uuid.uuid4().hex[:8]
        tool_calls.append({"id": tc_id, "name": name, "args": args})

    usage = {
        "prompt_tokens": resp_json.get("prompt_eval_count", 0),
        "completion_tokens": resp_json.get("eval_count", 0),
    }
    return {"content": content, "tool_calls": tool_calls, "usage": usage}


def _raw_post(
    url: str,
    payload: Dict,
    stream: bool = False,
    timeout_seconds: Optional[float] = None,
) -> Any:
    """Single HTTP POST.  Non-stream → dict.  Stream → generator of delta str."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    timeout = 180.0
    if timeout_seconds is not None:
        try:
            timeout = max(1.0, float(timeout_seconds))
        except Exception:
            timeout = 180.0

    if stream:
        return _stream_deltas(req, timeout_seconds=timeout)

    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {e.code}: {body}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e


def _stream_deltas(
    req: urllib.request.Request,
    timeout_seconds: Optional[float] = None,
    cancel_check: Any = None,
) -> Generator[str, None, None]:
    """Yield text delta strings from a streaming Ollama response, stripping <think> blocks."""
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    _in_think = False
    _think_buf = ""
    timeout = 180.0
    if timeout_seconds is not None:
        try:
            timeout = max(1.0, float(timeout_seconds))
        except Exception:
            timeout = 180.0
    cancel_monitor = None
    try:
        with _opener.open(req, timeout=timeout) as resp:
            cancel_monitor = watch_stream_cancellation(resp, cancel_check)
            for raw in resp:
                if callable(cancel_check) and cancel_check():
                    raise RuntimeError("Model generation cancelled")
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    delta = (chunk.get("message") or {}).get("content", "")
                    if delta:
                        if _in_think:
                            # Accumulate until we find </think>
                            _think_buf += delta
                            if "</think>" in _think_buf:
                                _in_think = False
                                remainder = _think_buf.split("</think>", 1)[1]
                                _think_buf = ""
                                if remainder:
                                    yield remainder
                        else:
                            if "<think>" in delta:
                                parts = delta.split("<think>", 1)
                                if parts[0]:
                                    yield parts[0]
                                _in_think = True
                                _think_buf = parts[1] if len(parts) > 1 else ""
                                # Check if </think> is already in this chunk
                                if "</think>" in _think_buf:
                                    _in_think = False
                                    remainder = _think_buf.split("</think>", 1)[1]
                                    _think_buf = ""
                                    if remainder:
                                        yield remainder
                            else:
                                yield delta
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        raise RuntimeError(f"Ollama streaming failed: {e}") from e
    finally:
        if cancel_monitor is not None:
            cancel_monitor.set()


# ─────────────────────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────────────────────


def default_ollama_context_window() -> int:
    for value in (os.getenv("KOTO_OLLAMA_NUM_CTX"), os.getenv("OLLAMA_NUM_CTX")):
        if value:
            try:
                if int(value) > 0:
                    return int(value)
            except (TypeError, ValueError):
                pass
    return 8192


def resolve_ollama_context_options(options=None, defaults=None) -> Dict[str, Any]:
    """Pure configuration projection shared by budget and native payload."""
    resolved = dict(options or {})
    nested = resolved.get("options")
    nested = nested if isinstance(nested, dict) else {}
    defaults = defaults or {}
    capacity = int(
        resolved.get("num_ctx")
        or nested.get("num_ctx")
        or defaults.get("num_ctx")
        or default_ollama_context_window()
    )
    output = int(
        resolved.get("num_predict")
        or nested.get("num_predict")
        or defaults.get("num_predict")
        or 4096
    )
    if capacity <= 0 or output <= 0:
        raise ValueError("Agent context and output token limits must be positive")
    declared = resolved.get("context_window_tokens") or resolved.get("context_window")
    resolved.update(
        {
            "num_ctx": capacity,
            "num_predict": output,
            "context_window_tokens": (
                min(capacity, int(declared)) if declared else capacity
            ),
            "reserved_output_tokens": max(
                output, int(resolved.get("reserved_output_tokens") or 0)
            ),
        }
    )
    return resolved


class OllamaLLMProvider(LLMProvider):
    """
    LLMProvider backed by a local Ollama instance.

    KernelAgent calls ``generate_content(prompt, system_instruction=…, tools=…)``
    on every ReAct step. The provider faithfully forwards the normalized
    request without adding product-layer behavior.

    Parameters
    ----------
    model : Ollama model tag (e.g. "qwen3:8b", "gemma3:4b").
            ``None`` (default) = 自动从已安装模型中选出最佳选项，每 60 秒重新检测一次。
    base_url : Ollama server base URL (default: http://localhost:11434)
    temperature : Sampling temperature
    num_predict : Max tokens to generate per call
    """

    # The current native text parser does not reconstruct tool-call fragments.
    # Keep local tool turns non-streaming rather than silently lose an action.
    streaming_tool_calls = False

    # 类级自动选模型缓存（所有 model=None 实例共享，60 秒 TTL）
    _auto_model: str = ""
    _auto_model_ts: float = 0.0
    _AUTO_MODEL_TTL: float = 60.0

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: str = _OLLAMA_BASE_URL,
        temperature: float = 0.7,
        num_predict: int = 4096,
        num_ctx: Optional[int] = None,
    ):
        self.model = model  # None 表示运行时自动选择
        self.base_url = base_url.rstrip("/")
        self._options: Dict[str, Any] = {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx or self._default_context_window(),
        }

    @staticmethod
    def _default_context_window() -> int:
        """An explicit request capacity, never inferred from a model's name."""
        return default_ollama_context_window()

    def context_options(self, options=None) -> Dict[str, Any]:
        """Return the exact generation limits used by both budget and request."""
        return resolve_ollama_context_options(options, getattr(self, "_options", {}))

    # ── LLMProvider interface ──────────────────────────────────────────────
    def _resolve_model(self) -> str:
        """
        返回实际使用的模型 TAG。
        - 初始化时指定了 model 则直接返回。
        - model=None 时对已安装模型进行评分，60 秒内缓存结果。
        """
        if self.model:
            return self.model
        # A user-selected model always wins over the historical automatic
        # scorer and its process-local cache.  Auto-selection below is only a
        # first-run fallback before the user has made a selection.
        try:
            from app.core.llm.local_model_runtime import get_configured_local_model_tag

            configured = get_configured_local_model_tag()
            if configured:
                return configured
        except Exception:
            pass
        now = time.time()
        if (
            OllamaLLMProvider._auto_model
            and (now - OllamaLLMProvider._auto_model_ts)
            < OllamaLLMProvider._AUTO_MODEL_TTL
        ):
            return OllamaLLMProvider._auto_model
        try:
            from app.core.llm.local_model_runtime import OllamaRuntime

            best = OllamaRuntime.pick_best_chat_model()
            if best:
                OllamaLLMProvider._auto_model = best
                OllamaLLMProvider._auto_model_ts = now
                logger.info(f"[OllamaLLMProvider] 自动选择模型: {best}")
                return best
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )
        return "qwen3.5:9b"  # 绝对保底，实际运行时 Ollama 应已安装

    def generate_content(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str = None,
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], Generator[Dict[str, Any], None, None]]:
        target = model or self._resolve_model()
        messages = _to_ollama_messages(prompt, system_instruction)
        ollama_tools = _to_ollama_tools(tools)

        # Merge per-call kwargs into options
        limits = self.context_options(kwargs)
        options = {
            **self._options,
            "num_ctx": limits["num_ctx"],
            "num_predict": limits["num_predict"],
        }
        for key in ("temperature", "top_p", "top_k"):
            if kwargs.get(key) is not None:
                options[key] = kwargs[key]

        payload: Dict[str, Any] = {
            "model": target,
            "messages": messages,
            "stream": stream,
            "options": options,
        }
        if ollama_tools:
            payload["tools"] = ollama_tools
        # File-task calls explicitly opt out of Qwen3's long internal reasoning
        # phase.  Keep the field family-scoped so non-Qwen models keep their
        # normal Ollama-compatible payload.
        if kwargs.get("think") is not None and _supports_thinking_toggle(target):
            payload["think"] = bool(kwargs["think"])

        url = f"{self.base_url}/api/chat"
        timeout_seconds = kwargs.get("call_timeout")

        if stream:
            return self._stream_chunks(
                url,
                payload,
                timeout_seconds=timeout_seconds,
                cancel_check=kwargs.get("_cancel_check"),
            )

        resp_json = _raw_post(
            url, payload, stream=False, timeout_seconds=timeout_seconds
        )
        return _parse_ollama_response(resp_json)

    def get_token_count(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str,
    ) -> int:
        # Ollama has no token-count endpoint; estimate via char/3 (matches GPT-4 rule-of-thumb)
        if isinstance(prompt, str):
            return max(1, len(prompt) // 3)
        total = 0
        for msg in prompt or []:
            c = msg.get("content") or msg.get("text") or ""
            total += max(1, len(str(c)) // 3)
        return total or 1

    # ── Internal ─────────────────────────────────────────────────────────

    def _stream_chunks(
        self,
        url: str,
        payload: Dict,
        timeout_seconds: Optional[float] = None,
        cancel_check: Any = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Yield Kernel-compatible chunks from a streaming Ollama call."""
        payload = {**payload, "stream": True}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        for delta in _stream_deltas(
            req, timeout_seconds=timeout_seconds, cancel_check=cancel_check
        ):
            yield {"content": delta, "delta": delta, "tool_calls": [], "usage": {}}
