# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
WebToolsBridgePlugin — legacy web/tool_registry 桥接器。

历史上 web 层（Flask 路由直调）与应用层（UnifiedAgent）各自有独立注册表，
此插件用于把 web.tool_registry 中的工具注入 ToolRegistry。

当前仓库已不再提供 web.tool_registry；默认启动路径也不再加载该桥接器。
保留此插件仅用于兼容旧环境，缺失 legacy 模块时应静默返回空工具列表。
"""

import importlib
import logging
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)


class WebToolsBridgePlugin(AgentPlugin):
    """桥接 web/tool_registry.ToolRegistry 的全部工具"""

    @property
    def name(self) -> str:
        return "WebToolsBridge"

    @property
    def description(self) -> str:
        return (
            "Bridges web-layer tools: WeChat, calendar, reminders, web search, "
            "browser automation, clipboard, file I/O, Excel analysis, document gen, etc."
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        try:
            mod = importlib.import_module("web.tool_registry")
            WebRegistry = getattr(mod, "ToolRegistry")
            web_reg = WebRegistry()
        except ModuleNotFoundError as exc:
            missing_name = getattr(exc, "name", None)
            if missing_name == "web.tool_registry" or "web.tool_registry" in str(exc):
                logger.debug(
                    "[WebToolsBridgePlugin] legacy web.tool_registry 不存在，跳过桥接"
                )
                return []
            logger.warning(f"[WebToolsBridgePlugin] 无法加载 web/tool_registry: {exc}")
            return []
        except Exception as exc:
            logger.warning(f"[WebToolsBridgePlugin] 无法加载 web/tool_registry: {exc}")
            return []

        tools = []
        for tool_name, tool_info in web_reg._tools.items():
            raw_params = tool_info.get("parameters", {})
            # 转换 JSON Schema (lowercase types) → Gemini 格式 (uppercase TYPE)
            converted_params = _convert_schema(raw_params)

            tools.append(
                {
                    "name": tool_name,
                    "func": _make_wrapper(web_reg, tool_name),
                    "description": tool_info.get("description", ""),
                    "parameters": converted_params,
                }
            )

        logger.info(f"[WebToolsBridgePlugin] 桥接了 {len(tools)} 个 web 层工具")
        return tools


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

_TYPE_MAP = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def _convert_schema(schema: Dict) -> Dict:
    """递归将 JSON Schema 的小写 type 转换为 Gemini API 要求的大写形式"""
    if not isinstance(schema, dict):
        return schema

    result = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            result[k] = _TYPE_MAP.get(v.lower(), v.upper())
        elif isinstance(v, dict):
            result[k] = _convert_schema(v)
        elif isinstance(v, list):
            result[k] = [_convert_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def _make_wrapper(registry, tool_name: str):
    """
    创建一个闭包，将调用转发到 web ToolRegistry.execute()，
    并将返回的 dict 规范化为字符串（agent loop 要求 str 结果）。
    """

    def _wrapper(**kwargs):
        result = registry.execute(tool_name, kwargs)
        if isinstance(result, dict):
            import json

            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)

    _wrapper.__name__ = tool_name
    _wrapper.__doc__ = f"Wrapper for web tool: {tool_name}"
    return _wrapper
