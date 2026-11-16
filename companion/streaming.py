"""Accumulate compatible SSE tool calls; only complete proposals may be written."""

import json
import re
import time

from .contracts import CompanionError, OperationCancelled


def answer_prefix(arguments):
    match = re.match(r'^\s*\{\s*"text"\s*:\s*', arguments)
    if not match:
        return ""
    value = arguments[match.end() :]
    decoder = json.JSONDecoder()
    try:
        text, _ = decoder.raw_decode(value)
        return text if isinstance(text, str) else ""
    except ValueError:
        # A network chunk can end inside a JSON escape or Unicode escape.
        for trim in range(7):
            prefix = value[:-trim] if trim else value
            try:
                text = json.loads(prefix + '"')
                if isinstance(text, str):
                    return text
            except ValueError:
                pass
    return ""


def read_stream(response, cancelled, on_delta):
    content, calls, finish = "", {}, None
    metadata = {}
    previous, last_publish, wire_size, content_size = "", 0, 0, 0
    for line in response.iter_lines():
        if cancelled.is_set():
            raise OperationCancelled("已停止，旧结果未写入。")
        wire_size += len(line)
        if wire_size > 32 * 1024 * 1024:
            raise CompanionError("本轮模型输出过长，文档未改动。")
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            break
        packet = json.loads(raw)
        if isinstance(packet.get("model"), str):
            metadata["model"] = packet["model"][:200]
        if isinstance(packet.get("usage"), dict):
            # Keep numeric usage, never reasoning text or arbitrary provider
            # strings. The final SSE packet carries these counters too.
            usage = {
                k: v for k, v in packet["usage"].items() if type(v) in (int, float)
            }
            details = packet["usage"].get("completion_tokens_details", {})
            if isinstance(details, dict):
                usage["completion_tokens_details"] = {
                    k: v for k, v in details.items() if type(v) in (int, float)
                }
            metadata["usage"] = usage
        for choice in packet.get("choices", []):
            if choice.get("index", 0) != 0:
                continue
            finish = choice.get("finish_reason") or finish
            delta = choice.get("delta") or {}
            content += delta.get("content") or ""
            content_size += len(delta.get("content") or "")
            for call in delta.get("tool_calls") or []:
                index = call.get("index", 0)
                if type(index) is not int or not 0 <= index < 8:
                    raise CompanionError("模型工具调用无效，文档未改动。")
                target = calls.setdefault(
                    index,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                target["id"] += call.get("id") or ""
                content_size += len(call.get("id") or "")
                function = call.get("function") or {}
                for key in ("name", "arguments"):
                    target["function"][key] += function.get(key) or ""
                    content_size += len(function.get(key) or "")
            if content_size > 2 * 1024 * 1024:
                raise CompanionError("本轮模型输出过长，文档未改动。")
            preview = content
            if not preview and len(calls) == 1:
                function = next(iter(calls.values()))["function"]
                if function["name"] == "answer_user":
                    preview = answer_prefix(function["arguments"])
            now = time.monotonic()
            if (
                on_delta
                and preview
                and preview != previous
                and (not previous or now - last_publish >= 0.04)
            ):
                on_delta(preview[:18000])
                previous, last_publish = preview, now
    if not finish:
        raise CompanionError("模型输出中断，本次未修改文档。")
    message = {"role": "assistant", "content": content or None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {**metadata, "choices": [{"message": message, "finish_reason": finish}]}
