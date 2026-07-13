# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Provider-neutral user-facing errors for active chat stream handlers."""

from __future__ import annotations


def format_chat_error(error_str: str) -> str:
    """Map an exception string to a user-friendly Chinese error message."""
    err = (error_str or "").lower()

    # ── Location restriction ──────────────────────────────────────────
    if "location is not supported" in err or "failed_precondition" in err:
        return (
            "\u274c \u5730\u533a\u9650\u5236\n\n"
            "\u5f53\u524d\u4e91\u7aef AI \u670d\u52a1\u5728\u60a8\u6240\u5728\u7684\u5730\u533a\u4e0d\u53ef\u7528\u3002\n\n"
            "\U0001f4a1 \u89e3\u51b3\u65b9\u6848:\n"
            "1. \u68c0\u67e5 `config/deepseek_config.env` \u4e2d\u7684 `DEEPSEEK_API_BASE`\n"
            "2. \u68c0\u67e5\u4ee3\u7406\u548c\u7f51\u7edc\u8fde\u63a5\n"
            "3. \u6216\u542f\u52a8\u672c\u5730 Ollama \u6a21\u578b"
        )

    # ── Invalid API key ───────────────────────────────────────────────
    if "api key not valid" in err or (
        "invalid_argument" in err and "api key" in err
    ):
        return (
            "\u274c **API \u5bc6\u94a5\u65e0\u6548**\n\n"
            "\u8bf7\u68c0\u67e5\u60a8\u7684 DeepSeek API \u5bc6\u94a5:\n"
            "1. \u524d\u5f80 [DeepSeek \u5f00\u653e\u5e73\u53f0](https://platform.deepseek.com/api_keys) \u83b7\u53d6\u6709\u6548\u5bc6\u94a5\n"
            "2. \u5728 Koto \u8bbe\u7f6e\u9875\u9762\u66f4\u65b0 API \u5bc6\u94a5\uff08\u8bbe\u7f6e \u2192 API \u914d\u7f6e\uff09\n"
            "3. \u786e\u4fdd\u8d26\u6237\u4f59\u989d\u548c API \u6743\u9650\u6b63\u5e38\n\n"
            f"\u539f\u59cb\u9519\u8bef: `{error_str[:150]}`"
        )

    # ── Connection dropped ────────────────────────────────────────────
    if any(kw in err for kw in (
        "server disconnected", "disconnected without",
        "connection reset", "connection aborted",
    )):
        return (
            "\u274c **\u670d\u52a1\u5668\u8fde\u63a5\u4e2d\u65ad**\n\n"
            "\u4e0e\u5f53\u524d AI \u670d\u52a1\u7684\u8fde\u63a5\u88ab\u610f\u5916\u65ad\u5f00\uff0c\u8fd9\u901a\u5e38\u662f\u4e34\u65f6\u6027\u95ee\u9898\u3002\n\n"
            "\U0001f4a1 \u5efa\u8bae:\n"
            "1. \u7a0d\u7b49\u7247\u523b\u540e\u91cd\u65b0\u53d1\u9001\u6d88\u606f\n"
            "2. \u68c0\u67e5\u60a8\u7684\u7f51\u7edc\u8fde\u63a5\u7a33\u5b9a\u6027\n"
            "3. \u5982\u679c\u4f7f\u7528\u4ee3\u7406\uff0c\u8bf7\u786e\u8ba4\u4ee3\u7406\u8fde\u63a5\u6b63\u5e38\n"
            "4. \u5982\u95ee\u9898\u6301\u7eed\uff0c\u53ef\u5c1d\u8bd5\u5207\u6362\u5230\u5176\u4ed6\u6a21\u578b"
        )

    # ── Quota / rate limit ────────────────────────────────────────────
    if any(kw in err for kw in (
        "resource_exhausted", "quota", "rate limit", "429",
    )):
        return (
            "\u274c **API \u914d\u989d\u8d85\u9650**\n\n"
            "\u5f53\u524d API \u5bc6\u94a5\u7684\u8bf7\u6c42\u9891\u7387\u6216\u914d\u989d\u5df2\u8fbe\u4e0a\u9650\u3002\n\n"
            "\U0001f4a1 \u5efa\u8bae:\n"
            "1. \u7a0d\u7b49 1-2 \u5206\u949f\u540e\u91cd\u8bd5\n"
            "2. \u5728\u8bbe\u7f6e\u4e2d\u5207\u6362\u5230\u5176\u4ed6 API \u5bc6\u94a5\n"
            "3. \u6216\u68c0\u67e5 DeepSeek \u8d26\u6237\u4f59\u989d\u4e0e\u914d\u989d"
        )

    # ── Service unavailable ───────────────────────────────────────────
    if "unavailable" in err or "503" in err or "service unavailable" in err:
        return (
            "\u274c **AI \u670d\u52a1\u6682\u65f6\u4e0d\u53ef\u7528**\n\n"
            "\u5f53\u524d\u4e91\u7aef AI \u670d\u52a1\u65e0\u6cd5\u54cd\u5e94\uff0c\u53ef\u80fd\u6b63\u5728\u7ef4\u62a4\u4e2d\u3002\n\n"
            "\U0001f4a1 \u5efa\u8bae: \u7a0d\u7b49\u7247\u523b\u540e\u91cd\u8bd5\uff0c\u6216\u5207\u6362\u5230\u672c\u5730\u6a21\u578b"
        )

    # ── Timeout ───────────────────────────────────────────────────────
    if "deadline_exceeded" in err or "timed out" in err:
        return (
            "\u274c **\u8bf7\u6c42\u8d85\u65f6**\n\n"
            "\u6a21\u578b\u54cd\u5e94\u65f6\u95f4\u8fc7\u957f\uff0c\u8bf7\u6c42\u5df2\u8d85\u65f6\u3002\n\n"
            "\U0001f4a1 \u5efa\u8bae:\n"
            "1. \u5c1d\u8bd5\u7f29\u77ed\u60a8\u7684\u95ee\u9898\u6216\u5206\u6b65\u9aa4\u63d0\u95ee\n"
            "2. \u68c0\u67e5 DeepSeek \u670d\u52a1\u72b6\u6001\u6216\u5207\u6362\u5230\u672c\u5730\u6a21\u578b\n"
            "3. \u68c0\u67e5\u7f51\u7edc\u8fde\u63a5\u8d28\u91cf"
        )

    # ── Generic fallback ──────────────────────────────────────────────
    return f"\u274c \u53d1\u751f\u9519\u8bef: {error_str[:200]}"
