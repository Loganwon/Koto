# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
import logging
import os
import queue
import threading
import time
from typing import Any, Dict, Generator, List, Optional, Union

from .base import LLMProvider
from .gemini_config import get_gemini_api_key, load_gemini_config_env
from .model_capabilities import is_interactions_only_model

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

logger = logging.getLogger(__name__)


def _ensure_gemini_env_loaded() -> None:
    load_gemini_config_env(override=False)


def _normalize_proxy_url(proxy_value: str) -> str:
    value = str(proxy_value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value


def _iter_proxy_candidates() -> List[str]:
    candidates: List[str] = []

    force_proxy = str(os.getenv("FORCE_PROXY") or "").strip()
    if force_proxy and force_proxy.lower() not in {"auto", "system"}:
        candidates.append(_normalize_proxy_url(force_proxy))

    env_proxy = (
        os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
    )
    if env_proxy:
        candidates.append(_normalize_proxy_url(env_proxy))

    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                proxy_enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
                if proxy_enabled:
                    proxy_server = str(
                        winreg.QueryValueEx(key, "ProxyServer")[0] or ""
                    ).strip()
                    if proxy_server:
                        if "=" in proxy_server and ";" in proxy_server:
                            parsed_map = {}
                            for pair in proxy_server.split(";"):
                                if "=" not in pair:
                                    continue
                                key_name, value = pair.split("=", 1)
                                parsed_map[key_name.strip().lower()] = value.strip()
                            for proto in ("https", "http", "socks", "socks5"):
                                value = parsed_map.get(proto)
                                if value:
                                    candidates.append(_normalize_proxy_url(value))
                        else:
                            candidates.append(_normalize_proxy_url(proxy_server))
        except Exception:
            pass

    candidates.extend(
        [
            "http://127.0.0.1:7890",
            "http://127.0.0.1:10809",
            "http://127.0.0.1:1080",
        ]
    )

    deduped: List[str] = []
    seen = set()
    for item in candidates:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _ensure_gemini_proxy_configured() -> Optional[str]:
    import socket
    from urllib.parse import urlparse

    for proxy in _iter_proxy_candidates():
        try:
            parsed = urlparse(proxy)
            host = parsed.hostname
            port = parsed.port
            if not host or not port:
                continue

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                os.environ["HTTPS_PROXY"] = proxy
                os.environ["HTTP_PROXY"] = proxy
                return proxy
        except Exception:
            continue
    return None


# model_capabilities.is_interactions_only_model() is evaluated per-call (not baked
# at import time), so env overrides (KOTO_INTERACTIONS_ONLY_MODELS) are always live.


class GeminiProvider(LLMProvider):
    """Google Gemini specific implementation of LLMProvider (google.genai SDK)"""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0  # seconds
    RETRYABLE_STATUS_CODES = {429, 503}
    # 非流式调用整体超时（秒），超时后抛出 TimeoutError 触发本地模型兜底
    CALL_TIMEOUT: int = int(os.getenv("GEMINI_CALL_TIMEOUT", "15"))
    # 流式调用每个 chunk 之间的最长等待（秒）
    STREAM_CHUNK_TIMEOUT: int = int(os.getenv("GEMINI_STREAM_CHUNK_TIMEOUT", "15"))

    def __init__(self, api_key: str = None):
        if not api_key:
            _ensure_gemini_env_loaded()

        self.api_key = get_gemini_api_key(api_key, ensure_loaded=False)
        self._api_base = os.getenv("GEMINI_API_BASE", "").strip()
        self.client = None

        if not genai or not types:
            logger.warning("google.genai package not installed")
            return

        if self.api_key:
            try:
                self.client = self._make_client(self.api_key)
            except Exception as exc:
                logger.error(f"Failed to initialize google.genai client: {exc}")
                self.client = None
        else:
            logger.warning("No Google API KEY provided")

    def _make_client(self, api_key: str):
        """Build a genai.Client with bounded HTTP timeouts.

        This avoids indefinite socket/connect hangs in upstream HTTP layers.
        """
        if not genai:
            return None

        opts_kwargs: Dict[str, Any] = {"api_version": "v1beta"}
        if self._api_base:
            opts_kwargs["base_url"] = self._api_base

        # Keep connect timeout strict; read timeout should exceed both
        # non-stream and stream-chunk guard rails.
        _connect_timeout = float(os.getenv("GEMINI_CONNECT_TIMEOUT", "10"))
        _read_timeout = float(
            os.getenv(
                "GEMINI_READ_TIMEOUT",
                str(max(self.CALL_TIMEOUT + 5, self.STREAM_CHUNK_TIMEOUT + 5)),
            )
        )

        try:
            import httpx
            from google.genai._api_client import HttpOptions as _HttpOptions

            _ensure_gemini_proxy_configured()
            _httpx_client = httpx.Client(
                timeout=httpx.Timeout(_read_timeout, connect=_connect_timeout),
                verify=True,
            )
            opts_kwargs["httpx_client"] = _httpx_client
            return genai.Client(
                api_key=api_key, http_options=_HttpOptions(**opts_kwargs)
            )
        except Exception as exc:
            logger.warning("[GeminiProvider] httpx timeout client init failed: %s", exc)
            try:
                from google.genai._api_client import HttpOptions as _HttpOptions

                return genai.Client(
                    api_key=api_key, http_options=_HttpOptions(**opts_kwargs)
                )
            except Exception:
                logger.warning(
                    "[GeminiProvider] HttpOptions init failed, using default client"
                )
                return genai.Client(api_key=api_key)

    def _get_client(self):
        """Return a genai.Client for the current request.

        Priority: per-request key in flask.g (set by auth middleware) >
                  instance key (set at construction, from env).
        A fresh client is returned only when the request key differs from
        the instance key, avoiding unnecessary object creation.
        """
        try:
            from flask import g as flask_g

            request_key = getattr(flask_g, "api_key", None)
        except RuntimeError:
            # Outside Flask request context (background threads, tests)
            request_key = None

        if request_key and request_key != self.api_key and genai:
            try:
                return self._make_client(request_key)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Silenced exception caught", exc_info=True
                )
        return self.client

    def generate_content(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        model: str = "gemini-2.5-flash",
        system_instruction: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], Generator[Dict[str, Any], None, None]]:
        client = self._get_client()
        if not client or not types:
            raise ImportError("google.genai client not initialized")

        # Route interactions-only models through Interactions API transparently
        if is_interactions_only_model(model):
            result = self._call_via_interactions_api(
                model, prompt, sys_instruction=system_instruction, stream=stream
            )
            if not stream and isinstance(result, dict):
                self._track_usage(
                    model,
                    result.get("usage"),
                    skill_id=kwargs.get("skill_id"),
                    session_id=kwargs.get("session_id"),
                )
            return result

        try:
            config = types.GenerateContentConfig(
                temperature=kwargs.get("temperature", 0.7),
                top_p=kwargs.get("top_p", 0.95),
                top_k=kwargs.get("top_k", 64),
                max_output_tokens=kwargs.get("max_tokens", 8192),
                response_mime_type=kwargs.get("response_mime_type", "text/plain"),
                system_instruction=system_instruction,
                tools=self._format_tools(tools),
            )

            contents = self._format_prompt(prompt)

            if stream:
                last_stream_exc = None
                for _stream_attempt in range(self.MAX_RETRIES):
                    try:
                        response_iter = client.models.generate_content_stream(
                            model=model,
                            contents=contents,
                            config=config,
                        )
                        return self._stream_generator(
                            response_iter,
                            model=model,
                            skill_id=kwargs.get("skill_id"),
                            session_id=kwargs.get("session_id"),
                        )
                    except Exception as _se:
                        last_stream_exc = _se
                        _se_str = str(_se)
                        _se_retryable = (
                            "SSL" in _se_str
                            or "UNEXPECTED_EOF" in _se_str
                            or "RemoteDisconnected" in _se_str
                            or "ConnectionReset" in _se_str
                            or "429" in _se_str
                            or "503" in _se_str
                        )
                        if not _se_retryable or _stream_attempt == self.MAX_RETRIES - 1:
                            raise
                        _delay = self.RETRY_BASE_DELAY * (2**_stream_attempt)
                        logger.warning(
                            f"Stream connect error (attempt {_stream_attempt + 1}/{self.MAX_RETRIES}), "
                            f"retrying in {_delay:.1f}s: {_se}"
                        )
                        time.sleep(_delay)
                raise last_stream_exc  # unreachable but satisfies type checker

            # File-task style calls can override the hard timeout per request.
            result = self._call_with_retry(
                model,
                contents,
                config,
                client,
                timeout_seconds=kwargs.get("call_timeout"),
            )
            self._track_usage(
                model,
                result.get("usage"),
                skill_id=kwargs.get("skill_id"),
                session_id=kwargs.get("session_id"),
            )
            return result

        except Exception as exc:
            logger.error(f"Gemini generation error: {exc}")
            raise

    def _call_with_retry(
        self,
        model: str,
        contents,
        config,
        client=None,
        timeout_seconds: Optional[float] = None,
    ):
        """Call generate_content with exponential backoff retry on 429/503.

        Uses a hard wall-clock timeout wrapper (daemon thread) so Koto never
        blocks indefinitely even if upstream SDK retries get stuck.
        """
        if client is None:
            client = self._get_client()

        effective_timeout = float(
            timeout_seconds if timeout_seconds is not None else self.CALL_TIMEOUT
        )

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._run_call_with_hard_timeout(
                    lambda: client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config,
                    ),
                    timeout_seconds=effective_timeout,
                    timeout_message=(
                        f"LLM call timed out after {effective_timeout:g}s "
                        f"(model={model})"
                    ),
                )
                return self._format_response(response)
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                exc_str = str(exc)
                exc_lower = exc_str.lower()

                # Timeout-like failures should fail fast to avoid perceived hangs.
                if "timeout" in exc_lower or "timed out" in exc_lower:
                    raise TimeoutError(
                        f"LLM call timed out (model={model}, timeout={effective_timeout:g}s)"
                    ) from exc

                is_retryable = (
                    (status_code and status_code in self.RETRYABLE_STATUS_CODES)
                    or "429" in exc_str
                    or "503" in exc_str
                    or "RESOURCE_EXHAUSTED" in exc_str
                    # Transient SSL / network drops
                    or "SSL" in exc_str
                    or "UNEXPECTED_EOF" in exc_str
                    or "RemoteDisconnected" in exc_str
                    or "ConnectionReset" in exc_str
                    or "ConnectionError" in exc_str
                )
                if not is_retryable or attempt == self.MAX_RETRIES - 1:
                    raise
                delay = self.RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    f"Retryable error (attempt {attempt + 1}/{self.MAX_RETRIES}), "
                    f"retrying in {delay:.1f}s: {exc}"
                )
                time.sleep(delay)

    @staticmethod
    def _run_call_with_hard_timeout(
        callable_fn, timeout_seconds: float, timeout_message: str
    ):
        """Run callable in a daemon thread and fail fast on timeout.

        Daemon thread ensures timed-out SDK calls never block process shutdown.
        """
        _q: queue.Queue = queue.Queue(maxsize=1)

        def _runner():
            try:
                _q.put(("ok", callable_fn()))
            except Exception as exc:
                _q.put(("err", exc))

        _t = threading.Thread(target=_runner, daemon=True, name="gemini-hard-timeout")
        _t.start()

        try:
            status, payload = _q.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError(timeout_message) from exc

        if status == "err":
            raise payload
        return payload

    def get_token_count(
        self, prompt: Union[str, List[Dict[str, Any]]], model: str
    ) -> int:
        client = self._get_client()
        if not client or not types:
            return 0
        try:
            if isinstance(prompt, str):
                contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
            else:
                # Already in contents-list format
                contents = prompt  # type: ignore[assignment]
            response = client.models.count_tokens(
                model=model,
                contents=contents,
            )
            return int(getattr(response, "total_tokens", 0))
        except Exception:
            # Fallback: conservative char-based estimate
            text = prompt if isinstance(prompt, str) else str(prompt)
            return max(1, len(text) // 3)

    def _format_tools(self, tools: Optional[List[Any]]) -> Optional[List[Any]]:
        if not tools or not types:
            return None

        formatted_tools: List[Any] = []
        function_declarations: List[Any] = []

        for tool in tools:
            if isinstance(tool, dict) and tool.get("name"):
                function_declarations.append(
                    types.FunctionDeclaration(
                        name=tool.get("name"),
                        description=tool.get("description") or "",
                        parameters_json_schema=self._normalize_schema(
                            tool.get("parameters") or {}
                        ),
                    )
                )
            elif isinstance(tool, types.Tool):
                formatted_tools.append(tool)

        if function_declarations:
            formatted_tools.append(
                types.Tool(function_declarations=function_declarations)
            )

        return formatted_tools or None

    def _normalize_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize schema type values to JSON schema style expected by v2 SDK."""
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}

        def _walk(node: Any) -> Any:
            if isinstance(node, dict):
                out = {}
                for key, value in node.items():
                    if key == "type" and isinstance(value, str):
                        out[key] = value.lower()
                    else:
                        out[key] = _walk(value)
                return out
            if isinstance(node, list):
                return [_walk(item) for item in node]
            return node

        normalized = _walk(schema)
        if "type" not in normalized:
            normalized["type"] = "object"
        if "properties" not in normalized:
            normalized["properties"] = {}
        if "required" not in normalized:
            normalized["required"] = []
        return normalized

    def _format_prompt(self, prompt: Union[str, List[Dict[str, Any]]]):
        """Convert standard message format to google.genai content format."""
        if isinstance(prompt, str):
            return prompt

        contents: List[Dict[str, Any]] = []
        for msg in prompt:
            role = msg.get("role", "user")
            if role == "assistant":
                role = "model"
            elif role in ("function", "tool"):
                # Gemini only accepts "user" and "model" roles.
                # Function/tool responses are sent as user-role parts.
                role = "user"

            parts: List[Dict[str, Any]] = []

            # For function-response messages, only emit the function_response part
            if msg.get("role") in ("function", "tool"):
                fn_name = msg.get("name") or msg.get("tool_call_id") or "unknown_tool"
                parts.append(
                    {
                        "function_response": {
                            "name": fn_name,
                            "response": {"content": msg.get("content", "")},
                        }
                    }
                )
            else:
                # For model messages that carry raw parts (e.g. thinking models with
                # thought_signature), use those directly — they already contain text,
                # function_call, and thought_signature fields.
                if role == "model" and msg.get("parts"):
                    parts = list(msg["parts"])
                else:
                    text = msg.get("content")
                    if text:
                        parts.append({"text": str(text)})

                    for tool_call in msg.get("tool_calls", []) or []:
                        parts.append(
                            {
                                "function_call": {
                                    "name": tool_call.get("name"),
                                    "args": tool_call.get("args", {}),
                                }
                            }
                        )

                    if not parts and msg.get("parts"):
                        parts = list(msg["parts"])

            if parts:
                contents.append({"role": role, "parts": parts})

        return contents

    def _format_response(self, response: Any) -> Dict[str, Any]:
        """Convert google.genai response to standard dict format."""
        text = getattr(response, "text", "") or ""

        function_calls: List[Dict[str, Any]] = []
        raw_parts: List[Dict[str, Any]] = (
            []
        )  # preserves thought_signature for multi-turn tool calling
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(candidates[0].content, "parts", None) or []
            for part in parts:
                # Preserve thought parts (including thought_signature) required by thinking models
                if getattr(part, "thought", False):
                    raw_parts.append(
                        {
                            "thought": True,
                            "text": getattr(part, "text", "") or "",
                            "thought_signature": getattr(part, "thought_signature", "")
                            or "",
                        }
                    )
                    continue
                function_call = getattr(part, "function_call", None)
                if function_call:
                    fc_dict = {
                        "name": function_call.name,
                        "args": dict(function_call.args or {}),
                    }
                    function_calls.append(fc_dict)
                    # Preserve thought_signature at the Part level — required for
                    # thinking models in multi-turn tool-calling conversations.
                    part_dict: Dict[str, Any] = {"function_call": fc_dict}
                    part_thought_sig = getattr(part, "thought_signature", None) or ""
                    if part_thought_sig:
                        part_dict["thought_signature"] = part_thought_sig
                    raw_parts.append(part_dict)
                elif getattr(part, "text", None):
                    raw_parts.append({"text": part.text})

        usage_metadata = getattr(response, "usage_metadata", None)
        usage = {}
        if usage_metadata:
            usage = {
                "prompt_tokens": getattr(usage_metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(
                    usage_metadata, "candidates_token_count", 0
                ),
            }

        return {
            "content": text,
            "tool_calls": function_calls,
            "_raw_parts": raw_parts,  # re-injected into multi-turn history to preserve thought_signature
            "usage": usage,
        }

    def _stream_generator(
        self,
        response_iterator: Any,
        model: str,
        skill_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """Yield standardized chunks from google.genai stream.

        后台线程负责迭代 SDK 流并向队列投递 chunk；主生成器以 STREAM_CHUNK_TIMEOUT
        秒超时读取队列。若超时则认为云端流卡住，抛出 TimeoutError 触发兜底。
        """
        _q: queue.Queue = queue.Queue()
        _SENTINEL = object()

        def _feed():
            try:
                for chunk in response_iterator:
                    _q.put(chunk)
            except Exception as exc:
                _q.put(exc)
            finally:
                _q.put(_SENTINEL)

        _t = threading.Thread(target=_feed, daemon=True)
        _t.start()

        usage_tracked = False
        while True:
            try:
                item = _q.get(timeout=self.STREAM_CHUNK_TIMEOUT)
            except queue.Empty:
                raise TimeoutError(
                    f"Stream stalled: no chunk received in {self.STREAM_CHUNK_TIMEOUT}s"
                )
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            text = getattr(item, "text", "") or ""
            finish_reason = None
            candidates = getattr(item, "candidates", None) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
            usage_metadata = getattr(item, "usage_metadata", None)
            if usage_metadata and not usage_tracked:
                self._track_usage(
                    model,
                    usage_metadata,
                    skill_id=skill_id,
                    session_id=session_id,
                )
                usage_tracked = True
            yield {
                "content": text,
                "finish_reason": finish_reason,
            }

    def _call_via_interactions_api(
        self,
        model_id: str,
        prompt,
        sys_instruction: str = None,
        stream: bool = False,
        timeout: float = 45.0,
    ):
        """Route gemini-3.x / deep-research models via rc.interactions.create().

        - gemini-3.x  → background=False (sync, hard daemon-thread timeout)
        - deep-research-* → background=True (async create + status polling)

        Returns the same dict format as generate_content() for transparent routing.
        For stream=True, yields the full response as a single chunk (Interactions API
        has no token-level streaming).
        """
        normalized = model_id.lstrip("models/")
        is_deep_research = normalized.startswith("deep-research-")
        background = is_deep_research

        # Build plain-text input (Interactions API accepts text only)
        flat = self._flatten_prompt_to_text(prompt)
        if sys_instruction:
            flat = f"[系统指令]\n{sys_instruction}\n\n[用户输入]\n{flat}"
        flat = flat[:80000]

        rc = self._make_interactions_client(
            timeout=timeout, is_sync=not is_deep_research
        )

        if background:
            # Async: create() returns immediately, poll until done
            interaction = rc.interactions.create(
                agent=model_id,
                input=flat,
                background=True,
                stream=False,
            )
            start = time.time()
            iid = getattr(interaction, "id", None)
            status = getattr(interaction, "status", "")
            while (
                iid
                and status not in ("completed", "failed", "cancelled")
                and (time.time() - start) < timeout
            ):
                time.sleep(2)
                interaction = rc.interactions.get(iid)
                status = getattr(interaction, "status", "")
            if status not in ("completed", "failed", "cancelled"):
                try:
                    rc.interactions.cancel(iid)
                except Exception:
                    pass
                raise TimeoutError(
                    f"Interactions API polling timeout ({timeout}s) model={model_id}"
                )
        else:
            # Sync: create() blocks until model finishes. Wrap in daemon thread so the
            # hard timeout fires even when httpx chunked-transfer keeps the socket open.
            interaction = self._run_call_with_hard_timeout(
                lambda: rc.interactions.create(
                    model=model_id,
                    input=flat,
                    background=False,
                    stream=False,
                ),
                timeout_seconds=timeout,
                timeout_message=f"Interactions API sync timeout ({timeout}s) model={model_id}",
            )

        text = self._extract_interactions_text(interaction).strip()

        if stream:

            def _single_chunk():
                yield {"content": text, "finish_reason": "stop"}

            return _single_chunk()

        return {
            "content": text,
            "tool_calls": [],
            "usage": self._normalize_usage(interaction),
        }

    def _make_interactions_client(self, timeout: float, is_sync: bool):
        """Build a genai.Client tuned for Interactions API calls.

        For sync calls (is_sync=True) the HTTP read timeout equals `timeout` so the
        connection is not kept alive longer than necessary.  For async poll calls the
        per-request timeout can be much shorter.
        """
        try:
            import httpx
            from google.genai._api_client import HttpOptions as _HttpOptions

            connect_t = float(os.getenv("GEMINI_CONNECT_TIMEOUT", "10"))
            # Sync: daemon-thread enforces wall-clock timeout; httpx is a secondary
            # guard.  Async: poll requests are tiny, 45 s is plenty.
            read_t = (
                timeout
                if is_sync
                else float(os.getenv("GEMINI_INTERACTIONS_HTTP_TIMEOUT", "45"))
            )
            hc = httpx.Client(
                timeout=httpx.Timeout(read_t, connect=connect_t), verify=True
            )
            return genai.Client(
                api_key=self.api_key,
                http_options=_HttpOptions(api_version="v1beta", httpx_client=hc),
            )
        except Exception:
            return self.client

    @staticmethod
    def _extract_interactions_text(obj) -> str:
        """Extract plain text from an Interactions API response object."""
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        # Direct .text attribute — most common path for sync responses
        text = getattr(obj, "text", None)
        if text:
            return str(text)
        # Parts list (content / message object)
        parts = getattr(obj, "parts", None)
        if parts:
            return " ".join(str(p.text) for p in parts if getattr(p, "text", None))
        # Outputs list — background=True responses
        outputs = getattr(obj, "outputs", None)
        if outputs:
            chunks = [GeminiProvider._extract_interactions_text(o) for o in outputs]
            return "\n".join(c for c in chunks if c)
        return ""

    @staticmethod
    def _flatten_prompt_to_text(prompt) -> str:
        """Flatten a str or message-list prompt to plain text for Interactions API."""
        if isinstance(prompt, str):
            return prompt
        if not isinstance(prompt, list):
            return str(prompt)
        lines = []
        for msg in prompt:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                label = (
                    "\u52a9\u624b" if role in ("assistant", "model") else "\u7528\u6237"
                )
                lines.append(f"{label}: {content}")
        return "\n".join(lines)
